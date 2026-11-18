"""A person as the Helper: the runner's Helper turns are answered from a web page (/study/helper).

The page gets exactly what an AI Helper would receive (the images, the turn notes and the
Worker's message) plus the Helper's instructions as text, and answers each turn with a
message, a LOOK (Helper-controlled window) or DONE, under the same rules as the AI Helper.
"""
import asyncio
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from . import prompts
from .conditions import LOOKS_PER_TURN, TrialCondition
from .runner import NOT_FINISHED, RunStopped
from .views import parse_column_row

MAX_MESSAGE_CHARS = 1000


def _resolve(future: asyncio.Future, response: Dict[str, Any]) -> None:
    if not future.done():
        future.set_result(response)


def _stop(future: asyncio.Future) -> None:
    if not future.done():
        future.set_exception(RunStopped())


class HumanHelper:
    """The Helper role played by a person; ``publish`` sends each new screen to the page."""
    role = 'helper'
    is_human = True

    def __init__(self, publish: Callable[[Dict[str, Any]], None], looks_per_turn: int = LOOKS_PER_TURN):
        self._publish = publish
        self.looks_per_turn = looks_per_turn
        self._lock = threading.Lock()
        self._pending = None  # (event loop, future) while the runner waits for the person
        self._cancelled = False
        self.trial: Optional[TrialCondition] = None
        self.trial_index = 0
        self.trial_total: Optional[int] = None
        self.instructions: List[str] = []
        self.chat: List[Dict[str, str]] = []
        self.view: Dict[str, Any] = {'state': 'idle'}  # the latest screen, for a page that (re)connects
        self._looks_left = looks_per_turn
        self._done_used = False
        self._last_kind: Optional[str] = None
        self._asked_at = 0.0

    # --- runner interface -------------------------------------------------------------------
    def start_trial(self, trial: TrialCondition, disclose: bool = True) -> None:
        self.trial = trial
        self.trial_index += 1
        self.instructions = prompts.build_human_helper_instructions(trial, disclose)
        self.chat = []
        self._show(state='waiting', status='A new trial is starting.', images=[], notes=[])

    async def take_turn(self, observation, incoming: Optional[str], first: bool,
                        instruction: Optional[str] = None) -> Dict[str, Any]:
        if self._cancelled:
            raise RunStopped()
        if incoming:
            self.chat.append({'sender': 'worker', 'text': incoming})
        status = None
        if instruction is None:  # a new turn, not a reply after a LOOK or DONE
            self._looks_left, self._done_used = self.looks_per_turn, False
            if not first and not incoming:
                status = 'The Worker did not send a message.'
        elif self._last_kind == 'done':
            status = (f"You pressed DONE, but the game checked the Worker's board: {NOT_FINISHED} "
                      "The Worker has been told too. Now send the Worker a message.")
        elif self._last_kind == 'look':
            status = 'Your window has moved. Now send the Worker a message.'
        future = asyncio.get_running_loop().create_future()
        with self._lock:
            if self._cancelled:  # stopped between the check above and now
                raise RunStopped()
            self._pending = (asyncio.get_running_loop(), future)
            self._asked_at = time.perf_counter()
        self._show(state='your_turn', status=status, notes=list(observation.notes),
                   images=[{'label': image.label, 'png_b64': image.png_b64} for image in observation.images],
                   can_look=self._can_look(), looks_left=self._looks_left, can_done=not self._done_used)
        try:
            return await future
        finally:
            with self._lock:
                self._pending = None

    def cancel(self) -> None:
        """The run was stopped: release a turn that is waiting for the person."""
        self._cancelled = True
        with self._lock:
            pending, self._pending = self._pending, None
        if pending:
            loop, future = pending
            loop.call_soon_threadsafe(_stop, future)
        self._show(state='stopped', status='The researcher stopped the run.')

    # --- page interface ---------------------------------------------------------------------
    def submit(self, data: Dict[str, Any]) -> Optional[str]:
        """Answer the waiting turn from the page; returns an error for the page, or None."""
        kind = (data or {}).get('kind')
        with self._lock:
            if self._pending is None:
                return 'It is not your turn yet.'
            if kind == 'message':
                text = str(data.get('text') or '').strip()
                if not text:
                    return 'Write a message first.'
                if len(text) > MAX_MESSAGE_CHARS:
                    return f'Messages can be at most {MAX_MESSAGE_CHARS} characters.'
                response = {'message': text, 'actions': [], 'raw_text': f'MESSAGE: "{text}"'}
                screen = dict(state='worker_turn', status='The Worker is taking its turn.')
            elif kind == 'look':
                cell = parse_column_row(str(data.get('cell') or ''))
                if not self._can_look() or self._looks_left <= 0:
                    return 'You cannot move your window now.'
                if cell is None:
                    return 'Choose a cell such as C3.'
                self._looks_left -= 1
                label = str(data['cell']).strip().upper()
                response = {'message': None, 'actions': [{'action': 'look', 'position': list(cell)}],
                            'raw_text': f'LOOK at {label}'}
                screen = dict(state='waiting', status=f'Moving your window to {label}.')
            elif kind == 'done':
                if self._done_used:
                    return 'The board was already checked this turn.'
                self._done_used = True
                response = {'message': None, 'actions': [{'action': 'done'}], 'raw_text': 'DONE'}
                screen = dict(state='waiting', status="Checking the Worker's board.")
            else:
                return 'Unknown action.'
            loop, future = self._pending
            self._pending = None  # one answer per turn, even if the page sends twice
            response.update(error=False, latency_s=0.0,
                            response_s=round(time.perf_counter() - self._asked_at, 3))
            self._last_kind = kind
            if kind == 'message':
                self.chat.append({'sender': 'helper', 'text': response['message']})
        self._show(**screen)
        loop.call_soon_threadsafe(_resolve, future, response)
        return None

    def notify(self, event: Dict[str, Any]) -> None:
        """Run events the person should see: the number of trials and how each trial ended."""
        kind = event.get('type')
        if kind == 'run_started':
            self.trial_total = len(event.get('trials') or [])
        elif kind == 'trial_finished':
            result = event['result']
            outcome = (f"Trial finished: the puzzle is solved ({result['turns']} turns)." if result['solved'] else
                       f"Trial finished: the turn limit was reached ({result['correct_target_cells']} of "
                       f"{result['target_cells']} pieces in place).")
            self._show(state='trial_over', status=outcome)
        elif kind == 'run_finished':
            self._show(state='run_over', status='All trials are finished. Thank you!'
                       if event.get('status') == 'completed' else 'The run has ended.')

    # --- helpers ----------------------------------------------------------------------------
    def _can_look(self) -> bool:
        trial = self.trial
        return bool(trial and trial.window_cells and trial.fov_control == 'helper' and self._looks_left > 0)

    def _show(self, **screen: Any) -> None:
        trial = self.trial
        self.view = {
            'trial_index': self.trial_index, 'trial_total': self.trial_total,
            'experiment': trial.experiment if trial else None,
            'helper_window': bool(trial and trial.window_cells and trial.fov_control == 'helper'),
            'instructions': self.instructions, 'chat': list(self.chat),
            'images': self.view.get('images', []), 'notes': self.view.get('notes', []),
            'can_look': False, 'looks_left': 0, 'can_done': False, 'status': None, **screen,
        }
        self._publish(self.view)
