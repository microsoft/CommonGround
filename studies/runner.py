"""Runs a full study schedule between a Worker and a Helper and reports every step.

The same runner drives the headless command line and the live web observer. It
talks to its agents only through ``take_turn(observation, incoming, first,
instruction)``, so tests can substitute scripted agents.
"""
import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .conditions import LOOKS_PER_TURN, StudyConfig, TrialCondition, build_schedule
from .environment import StudyEnvironment
from .logging_utils import StudyLogger, new_run_id
from .metrics import count_spatial_deixis, count_verbal_alignments, count_words, mentions_piece_number
from .prompts import orientation_note
from .views import build_helper_observation, build_truth_images, build_worker_observation

BOARD_ACTIONS = ('place', 'move', 'remove')
NOT_FINISHED = "The puzzle is not finished yet."


def helper_look_prompt(looks_left: int) -> str:
    """The Helper's follow-up instruction after it moved its window."""
    text = ("You moved your window; the board image above shows the new view. Anything else you wrote "
            "together with LOOK was not sent to the Worker. ")
    if looks_left > 0:
        return text + "Now reply to the Worker with a MESSAGE (or LOOK somewhere else first)."
    return text + ("That was your last LOOK for this turn: reply to the Worker with a MESSAGE now. "
                   "You can LOOK again next turn.")


def helper_followup_prompt(looked: bool, looks_left: int, done_failed: bool) -> str:
    """The Helper's follow-up instruction after a LOOK, a failed DONE, or both."""
    if not done_failed:
        return helper_look_prompt(looks_left)
    text = (f"You declared the puzzle finished (DONE), but the game checked the Worker's board: {NOT_FINISHED} "
            "The Worker has been told too. Anything else you wrote together with DONE was not sent to the Worker. ")
    if looked:
        text += "You also moved your window; the board image above shows the new view. "
    return text + "Now reply to the Worker with a MESSAGE."


class RunStopped(Exception):
    """The run was stopped by the user."""


class RunAborted(Exception):
    """Too many consecutive model errors, so continuing would only burn through the schedule."""


def _images(observation) -> List[Dict[str, str]]:
    return [{'label': image.label, 'png_b64': image.png_b64} for image in observation.images]


def agent_model(agent) -> str:
    """The model an agent runs on: 'human' for a person, else its client's deployment."""
    if getattr(agent, 'is_human', False):
        return 'human'
    from utils import settings
    client = getattr(agent, 'ai_client', None)
    return getattr(client, 'deployment', None) or settings.OPENAI_GPT4_DEPLOYMENT


class StudyRunner:
    def __init__(self, config: StudyConfig, worker, helper, *, max_turns: int = 20,
                 looks_per_turn: int = LOOKS_PER_TURN,
                 trial_limit: Optional[int] = None, emit: Optional[Callable[[Dict[str, Any]], None]] = None,
                 log_dir: Optional[Path] = None, run_id: Optional[str] = None, save_images: bool = True,
                 max_consecutive_errors: int = 3):
        self.config = config
        self.worker = worker
        self.helper = helper
        self.max_turns = max_turns
        self.looks_per_turn = looks_per_turn
        self.max_consecutive_errors = max_consecutive_errors
        self.run_id = run_id or new_run_id(config.experiment)
        schedule = build_schedule(config)
        self.schedule: List[TrialCondition] = schedule[:trial_limit] if trial_limit else schedule
        self._emit_callback = emit
        from utils import settings
        # Recorded with every run, so runs on different models can be told apart and pooled correctly.
        self.worker_model = agent_model(worker)
        self.helper_model = agent_model(helper)
        self.model = (self.worker_model if self.worker_model == self.helper_model
                      else f"worker {self.worker_model}, helper {self.helper_model}")
        if log_dir is None:
            log_dir = Path(settings.LOG_DIR) / 'studies'
        self.run_dir = Path(log_dir) / self.run_id
        self.logger = StudyLogger(self.run_dir, save_images=save_images)
        self._resume = threading.Event()
        self._resume.set()
        self._stopped = threading.Event()
        self._consecutive_errors: Dict[str, int] = {}
        self.results: List[Dict[str, Any]] = []
        self.status = 'idle'

    # --- controls (safe to call from another thread) -------------------------------------
    def pause(self) -> None:
        if self.status == 'running':
            self._resume.clear()
            self.status = 'paused'
            self._emit('run_paused')

    def resume(self) -> None:
        if self.status == 'paused':
            self.status = 'running'
            self._resume.set()
            self._emit('run_resumed')

    def stop(self) -> None:
        self._stopped.set()
        self._resume.set()
        for agent in (self.worker, self.helper):
            cancel = getattr(agent, 'cancel', None)  # e.g. a human Helper waiting for input
            if callable(cancel):
                cancel()

    # --- events ---------------------------------------------------------------------------
    def _emit(self, event_type: str, **data: Any) -> None:
        event = {'type': event_type, 'run_id': self.run_id, 'ts': time.time(), **data}
        self.logger.write(event)
        if self._emit_callback:
            try:
                self._emit_callback(event)
            except Exception:  # an observer problem must never break the experiment
                import logging
                logging.getLogger(__name__).exception('Study event callback failed')

    async def _checkpoint(self) -> None:
        while not self._resume.is_set():
            await asyncio.sleep(0.1)
        if self._stopped.is_set():
            raise RunStopped()

    def model_settings(self) -> Optional[Dict[str, Any]]:
        """How model requests were actually sent (token limit, temperature), if a model client is in use.

        Known only after the first call, since the client adapts to what the model accepts.
        """
        return self._client_settings(self.worker)

    def helper_model_settings(self) -> Optional[Dict[str, Any]]:
        """The Helper's settings, when it uses a different client from the Worker (else None)."""
        if getattr(self.helper, 'ai_client', None) is getattr(self.worker, 'ai_client', None):
            return None
        return self._client_settings(self.helper)

    @staticmethod
    def _client_settings(agent) -> Optional[Dict[str, Any]]:
        client = getattr(agent, 'ai_client', None)
        describe = getattr(client, 'describe_settings', None)
        return describe() if callable(describe) else None

    # --- run ------------------------------------------------------------------------------
    async def run(self) -> Dict[str, Any]:
        self.status = 'running'
        self._emit('run_started', config=self.config.to_dict(), max_turns=self.max_turns, model=self.model,
                   worker_model=self.worker_model, helper_model=self.helper_model,
                   trials=[trial.to_dict() for trial in self.schedule])
        reason = None
        try:
            for index, trial in enumerate(self.schedule, start=1):
                await self._checkpoint()
                self.results.append(await self._run_trial(trial, index))
                self.logger.write_trials(self.results)
            self.status = 'completed'
        except RunStopped:
            self.status, reason = 'stopped', 'Stopped by the user'
        except RunAborted as exc:
            self.status, reason = 'aborted', str(exc)
        except Exception as exc:
            self.status, reason = 'failed', f"{type(exc).__name__}: {exc}"
            self._emit('error', message=reason)
        solved = sum(1 for result in self.results if result['solved'])
        summary = {'run_id': self.run_id, 'status': self.status, 'reason': reason, 'model': self.model,
                   'worker_model': self.worker_model, 'helper_model': self.helper_model,
                   'model_settings': self.model_settings(), 'config': self.config.to_dict(),
                   'trials_completed': len(self.results),
                   'trials_total': len(self.schedule), 'trials_solved': solved, 'results': self.results}
        helper_settings = self.helper_model_settings()
        if helper_settings is not None:
            summary['helper_model_settings'] = helper_settings
        self.logger.write_summary(summary)
        self._emit('run_finished', status=self.status, reason=reason, trials_completed=len(self.results),
                   trials_total=len(self.schedule), trials_solved=solved, model_settings=summary['model_settings'])
        self.logger.close()
        return summary

    async def _run_trial(self, trial: TrialCondition, index: int) -> Dict[str, Any]:
        env = StudyEnvironment(trial)
        disclose = self.config.disclose_view_differences
        self.worker.start_trial(trial, disclose)
        self.helper.start_trial(trial, disclose)
        stats = {'helper_messages': 0, 'worker_messages': 0, 'helper_words': 0, 'worker_words': 0,
                 'placements': 0, 'non_target_placements': 0, 'moves': 0, 'removals': 0, 'snapshots': 0,
                 'window_moves': 0, 'pointer_moves': 0, 'rejected_actions': 0, 'llm_errors': 0, 'llm_seconds': 0.0,
                 'spatial_deixis': 0, 'verbal_alignments': 0, 'held_back_messages': 0, 'helper_looks': 0,
                 'done_claims': 0, 'false_done_claims': 0,
                 'worker_piece_number_messages': 0, 'helper_piece_number_messages': 0}
        self._emit('trial_started', trial=trial.to_dict(), index=index, total=len(self.schedule),
                   truth=build_truth_images(env), piece_names=env.piece_names)
        started = time.perf_counter()

        helper_message = await self._helper_turn(env, None, True, stats)
        for _ in range(self.max_turns):
            await self._checkpoint()
            env.turn += 1
            worker_message = await self._worker_turn(env, helper_message, stats)
            self._emit_state(env, 'worker_turn')
            if env.solved:
                break
            await self._checkpoint()
            helper_message = await self._helper_turn(env, worker_message, False, stats)
            self._emit_state(env, 'helper_turn')

        elapsed = time.perf_counter() - started
        correct_cells = sum(1 for y, row in enumerate(env.target_area) for x, tile in enumerate(row)
                            if tile is not None and env.work_area[y][x] == tile)
        result = {
            'model': self.model, 'worker_model': self.worker_model, 'helper_model': self.helper_model,
            'trial_id': trial.trial_id, 'experiment': trial.experiment, 'block': trial.block, 'trial': trial.trial,
            'complexity': trial.complexity, 'feedback': trial.feedback, 'alignment': trial.alignment,
            'transform_flip': trial.transform.flip, 'transform_degrees': trial.transform.degrees,
            'fov_size': trial.fov_size, 'fov_control': trial.fov_control,
            'solved': env.solved, 'turns': env.turn, 'elapsed_s': round(elapsed, 3),
            'correct_target_cells': correct_cells, 'target_cells': len(trial.tiles),
            'staging_pieces': trial.piece_count,
            'stem_angle': trial.figure.stem_angle if trial.figure else None,
            'stem_length': trial.figure.stem_length if trial.figure else None,
            **stats,
        }
        result['llm_seconds'] = round(result['llm_seconds'], 3)
        # Looking costs a human Helper time, so count each look like a Worker turn (the agents are not told).
        result['turns_plus_looks'] = env.turn + stats['helper_looks']
        self._emit('trial_finished', result=result, truth=build_truth_images(env))
        return result

    def _emit_state(self, env: StudyEnvironment, reason: str) -> None:
        window = env.window
        self._emit('state', reason=reason, turn=env.turn, solved=env.solved, truth=build_truth_images(env),
                   cursor=list(env.cursor), snapshots_sent=env.snapshots_sent,
                   window=None if window is None else {'x': window.x, 'y': window.y, 'size': window.size})

    def _record_call(self, role: str, response: Dict[str, Any], stats: Dict[str, Any]) -> None:
        stats['llm_seconds'] += response.get('latency_s', 0.0)
        if response.get('error'):
            stats['llm_errors'] += 1
            self._consecutive_errors[role] = self._consecutive_errors.get(role, 0) + 1
            # Client errors can run to dozens of lines; the first line is the useful part.
            summary = (response.get('raw_text') or 'Model call failed').strip().splitlines()[0][:300]
            self._emit('error', role=role, message=summary)
            if self._consecutive_errors[role] >= self.max_consecutive_errors:
                raise RunAborted(f"{self._consecutive_errors[role]} consecutive {role} model errors; last: {summary}")
        else:
            self._consecutive_errors[role] = 0

    def _record_message(self, env, role: str, message: Optional[str], stats: Dict[str, Any]) -> None:
        if not message:
            return
        stats[f'{role}_messages'] += 1
        stats[f'{role}_words'] += count_words(message)
        stats['spatial_deixis'] += count_spatial_deixis(message)
        stats['verbal_alignments'] += count_verbal_alignments(message)
        if mentions_piece_number(message):
            stats[f'{role}_piece_number_messages'] += 1
        self._emit('message', sender=role, turn=env.turn, text=message)

    def _remind_orientation(self, env, role: str, observation) -> None:
        """Repeat the rotation-study orientation statement every turn, not just at the start."""
        note = orientation_note(env.trial, role, self.config.disclose_view_differences)
        if note:
            observation.notes.insert(0, f"Reminder: {note}")

    async def _worker_turn(self, env, incoming: Optional[str], stats) -> Optional[str]:
        observation = build_worker_observation(env)
        self._remind_orientation(env, 'worker', observation)
        env.worker_notes = []
        self._emit('observation', role='worker', turn=env.turn, images=_images(observation),
                   notes=observation.notes)
        response = await self.worker.take_turn(observation, incoming, first=(not incoming and env.turn == 1))
        self._record_call('worker', response, stats)
        self._emit('agent_response', role='worker', turn=env.turn, message=response.get('message'),
                   actions=response.get('actions'), raw_text=response.get('raw_text'),
                   latency_s=response.get('latency_s'), error=response.get('error'))

        actions = response.get('actions') or []
        ordered = [a for a in actions if a['action'] != 'snapshot'] + [a for a in actions if a['action'] == 'snapshot']
        for action in ordered:
            ok, detail = env.apply_worker_action(action)
            self._emit('action_result', role='worker', turn=env.turn, action=action, ok=ok, detail=detail)
            if not ok:
                stats['rejected_actions'] += 1
                env.worker_notes.append(f"Your action {action['action'].upper()} was not carried out: {detail}.")
                continue
            kind = action['action']
            key = {'place': 'placements', 'move': 'moves', 'remove': 'removals', 'snapshot': 'snapshots',
                   'window': 'window_moves', 'point': 'pointer_moves'}[kind]
            stats[key] += 1
            if kind == 'place' and action['piece'] not in env.trial.tiles:
                stats['non_target_placements'] += 1  # a piece that is not in the target at all
        self._record_message(env, 'worker', response.get('message'), stats)
        return response.get('message')

    async def _helper_turn(self, env, incoming: Optional[str], first: bool, stats) -> Optional[str]:
        """One Helper turn: it may LOOK (up to looks_per_turn) and declare DONE (checked once per turn).

        After a LOOK or a failed DONE the Helper is asked again, so it replies knowing the new
        view or that the puzzle is not finished; its draft from that reply is not sent.
        """
        looks_left = self.looks_per_turn
        done_checked = False
        instruction = None
        last_step = self.looks_per_turn + 1          # one extra step for a failed DONE
        for step in range(last_step + 1):
            observation = build_helper_observation(env)
            self._remind_orientation(env, 'helper', observation)
            self._emit('observation', role='helper', turn=env.turn, images=_images(observation),
                       notes=observation.notes)
            response = await self.helper.take_turn(
                observation, incoming if step == 0 else None, first=(first and step == 0), instruction=instruction)
            self._record_call('helper', response, stats)
            # A human Helper's thinking time is not model time, so it is logged separately.
            human = {'response_s': response['response_s']} if 'response_s' in response else {}
            self._emit('agent_response', role='helper', turn=env.turn, message=response.get('message'),
                       actions=response.get('actions'), raw_text=response.get('raw_text'),
                       latency_s=response.get('latency_s'), error=response.get('error'), **human)
            looked = done_failed = False
            for action in response.get('actions') or []:
                if action.get('action') == 'done':
                    if done_checked:
                        continue  # the board has not changed since this turn's check
                    done_checked = True
                    stats['done_claims'] += 1
                    ok = env.solved
                    if not ok:
                        stats['false_done_claims'] += 1
                        done_failed = True
                        env.worker_notes.append(f"The Helper declared the puzzle finished, but it is not: {NOT_FINISHED}")
                    self._emit('action_result', role='helper', turn=env.turn, action=action, ok=ok,
                               detail='The puzzle is finished.' if ok else NOT_FINISHED)
                    continue
                if action.get('action') == 'look' and looks_left <= 0:
                    ok, detail = False, "LOOK was not carried out: you have already used your look this turn"
                else:
                    ok, detail = env.apply_helper_action(action)
                self._emit('action_result', role='helper', turn=env.turn, action=action, ok=ok, detail=detail)
                if ok:
                    stats['window_moves'] += 1
                    stats['helper_looks'] += 1
                    looks_left -= 1
                    looked = True
                else:
                    stats['rejected_actions'] += 1
            message = response.get('message')
            if (looked or done_failed) and step < last_step:
                # The Helper replies again knowing the new view or that the puzzle is not finished.
                if message:
                    stats['held_back_messages'] += 1
                    self._emit('message_held_back', role='helper', turn=env.turn, text=message)
                instruction = helper_followup_prompt(looked, looks_left, done_failed)
                continue
            self._record_message(env, 'helper', message, stats)
            return message
        return None
