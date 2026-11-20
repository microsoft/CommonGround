"""Live observer for visual-information studies (AI-AI, or a human Helper with an AI Worker).

Lets a researcher start, watch, pause and stop a study run in the browser. The
page is read-only with respect to the agents: it shows the same images and
dialogue the agents receive, plus observer-only ground truth. With a human
Helper, the person plays at ``/study/helper``, which shows only the Helper's view.

Starting a run spends model API budget, so the observer is off unless the
server is launched with ``python run.py observe`` (which also binds to localhost).
"""
import logging
import threading
from typing import Any, Dict, List, Optional

from flask import Blueprint, abort, current_app, render_template, session
from flask_socketio import emit, join_room

from studies.conditions import (
    COMPLEXITIES, COMPLEXITY_LABELS, DEFAULT_FOV_COMPLEXITIES, EXPERIMENTS, FOV_ALIGNMENTS, FOV_CONTROLS,
    DEFAULT_TRIALS_PER_BLOCK, StudyConfig, build_schedule)

logger = logging.getLogger(__name__)

observer_routes = Blueprint('observer', __name__)
ROOM = 'study_observer'
HUMAN_ROOM = 'study_human_helper'
MAX_TURNS_LIMIT = 50
HELPER_KINDS = ('ai', 'human')


class ObserverState:
    """The single active run and what a late-joining browser needs to catch up."""

    def __init__(self):
        self.lock = threading.Lock()
        self.runner = None
        self.human = None  # the HumanHelper of the latest run with a human Helper
        self.reset()

    def reset(self) -> None:
        self.status = 'idle'
        self.run_started: Optional[Dict[str, Any]] = None
        self.trial_started: Optional[Dict[str, Any]] = None
        self.results: List[Dict[str, Any]] = []
        self.chat: List[Dict[str, Any]] = []
        self.latest: Dict[str, Dict[str, Any]] = {}
        self.finished: Optional[Dict[str, Any]] = None

    def record(self, event: Dict[str, Any]) -> None:
        kind = event['type']
        if kind == 'run_started':
            self.reset()
            self.status, self.run_started = 'running', event
        elif kind == 'trial_started':
            self.trial_started, self.chat, self.latest = event, [], {}
        elif kind == 'message':
            self.chat.append(event)
        elif kind == 'observation':
            self.latest[f"observation_{event['role']}"] = event
        elif kind == 'agent_response':
            self.latest[f"agent_response_{event['role']}"] = event
        elif kind == 'state':
            self.latest['state'] = event
        elif kind == 'trial_finished':
            self.results.append(event)
        elif kind == 'run_paused':
            self.status = 'paused'
        elif kind == 'run_resumed':
            self.status = 'running'
        elif kind == 'run_finished':
            self.status, self.finished = 'finished', event

    def replay(self) -> List[Dict[str, Any]]:
        """Events that rebuild the current screen for a browser that just connected."""
        if not self.run_started:
            return []
        events = [self.run_started, *self.results]
        if self.trial_started and not self.finished:
            events.append(self.trial_started)
            events.extend(self.chat)
            events.extend(self.latest.values())
        if self.status == 'paused':
            events.append({'type': 'run_paused', 'run_id': self.run_started['run_id']})
        if self.finished:
            events.append(self.finished)
        return events


state = ObserverState()


def build_agents():
    """Create the Worker and Helper (patched in tests so no model is called)."""
    from studies.agents import create_agents
    return create_agents()


def _options() -> Dict[str, Any]:
    return {
        'experiments': list(EXPERIMENTS),
        'complexities': list(COMPLEXITIES),
        'complexity_labels': COMPLEXITY_LABELS,
        'default_fov_complexities': list(DEFAULT_FOV_COMPLEXITIES),
        'fov_controls': list(FOV_CONTROLS),
        'default_trials_per_block': DEFAULT_TRIALS_PER_BLOCK,
        'fov_alignments': list(FOV_ALIGNMENTS),
    }


def _int(value: Any, name: str, minimum: int, maximum: Optional[int] = None, default: Optional[int] = None):
    if value in (None, ''):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a whole number")
    if number < minimum or (maximum is not None and number > maximum):
        raise ValueError(f"{name} must be between {minimum} and {maximum if maximum is not None else 'any'}")
    return number


def parse_run_request(data: Dict[str, Any]):
    """Validate a start request; returns (config, run options). Raises ValueError.

    The run options include ``agents``: who plays the Helper.
    """
    experiment = data.get('experiment')
    complexities = data.get('complexities')
    if complexities is None:
        complexities = DEFAULT_FOV_COMPLEXITIES
    elif not isinstance(complexities, (list, tuple)) or not all(isinstance(c, str) for c in complexities):
        raise ValueError("Piece sets must be a list of names")
    config = StudyConfig(
        experiment=experiment,
        seed=_int(data.get('seed'), 'Seed', 0, default=0),
        complexity=data.get('complexity') or None,
        fov_control=data.get('fov_control') or None,
        trials_per_block=_int(data.get('trials_per_block'), 'Trials per block', 1, 20),
        disclose_view_differences=bool(data.get('disclose', True)),
        complexities=tuple(complexities),
        fov_alignment=data.get('fov_alignment') or 'aligned',
    )
    build_schedule(config)  # validates the factor choices
    helper = data.get('helper') or 'ai'
    if helper not in HELPER_KINDS:
        raise ValueError(f"Helper must be one of {', '.join(HELPER_KINDS)}")
    options = {
        'max_turns': _int(data.get('max_turns'), 'Max turns', 1, MAX_TURNS_LIMIT, 20),
        'trial_limit': _int(data.get('trial_limit'), 'Trial limit', 1, 200),
        'agents': {'helper': helper},
    }
    return config, options


@observer_routes.route('/observer')
def observer_page():
    if not current_app.config.get('OBSERVER_ENABLED'):
        abort(404)
    if current_app.config.get('RUN_STUDY_MODE') and session.get('role') != 'admin':
        abort(403)
    return render_template('observer.html', options=_options())


@observer_routes.route('/study/helper')
def human_helper_page():
    """The page for a person playing the Helper in a run started from the observer."""
    if not current_app.config.get('OBSERVER_ENABLED'):
        abort(404)
    return render_template('study_helper.html')


def register_observer_handlers(socketio, app) -> None:
    def enabled() -> bool:
        return bool(app.config.get('OBSERVER_ENABLED'))

    def broadcast(event: Dict[str, Any]) -> None:
        state.record(event)
        socketio.emit('study_event', event, room=ROOM)
        human = state.human
        if human is not None and event['type'] in ('run_started', 'trial_finished', 'run_finished'):
            human.notify(event)

    def publish_to_human(view: Dict[str, Any]) -> None:
        socketio.emit('human_helper_view', view, room=HUMAN_ROOM)

    def execute(runner) -> None:
        from ai.async_executor import get_async_executor
        try:
            get_async_executor().run_async(runner.run())
        except Exception as exc:
            logger.exception('Study run crashed')
            socketio.emit('observer_error', {'message': f"{type(exc).__name__}: {exc}"}, room=ROOM)
        finally:
            with state.lock:
                state.runner = None
                if state.status in ('running', 'paused'):
                    state.status = 'finished'

    @socketio.on('observer_join')
    def handle_join(data=None):
        if not enabled():
            emit('observer_error', {'message': 'The observer is not enabled on this server.'})
            return
        join_room(ROOM)
        emit('observer_state', {'status': state.status, 'events': state.replay()})

    @socketio.on('observer_start')
    def handle_start(data):
        if not enabled():
            return
        try:
            config, options = parse_run_request(data or {})
        except ValueError as exc:
            emit('observer_error', {'message': str(exc)})
            return
        agents = options.pop('agents')
        with state.lock:
            if state.runner is not None:
                emit('observer_error', {'message': 'A run is already in progress. Stop it first.'})
                return
            try:
                worker, helper = build_agents()
                human = None
                if agents['helper'] == 'human':
                    from studies.human import HumanHelper
                    helper = human = HumanHelper(publish_to_human)
                from studies.runner import StudyRunner
                runner = StudyRunner(config, worker, helper, emit=broadcast, **options)
            except Exception as exc:
                logger.exception('Could not start the study run')
                emit('observer_error', {'message': f"Could not start the run: {type(exc).__name__}: {exc}"})
                return
            state.runner = runner
            state.human = human
        socketio.start_background_task(execute, runner)

    def control(action: str):
        if not enabled():
            return
        with state.lock:
            runner = state.runner
        if runner is None:
            emit('observer_error', {'message': 'No run is in progress.'})
            return
        getattr(runner, action)()

    @socketio.on('observer_pause')
    def handle_pause(data=None):
        control('pause')

    @socketio.on('observer_resume')
    def handle_resume(data=None):
        control('resume')

    @socketio.on('observer_stop')
    def handle_stop(data=None):
        control('stop')

    @socketio.on('human_helper_join')
    def handle_human_join(data=None):
        if not enabled():
            emit('human_helper_error', {'message': 'The study is not running on this server.'})
            return
        join_room(HUMAN_ROOM)
        human = state.human
        emit('human_helper_view', human.view if human is not None else {'state': 'idle'})

    @socketio.on('human_helper_submit')
    def handle_human_submit(data):
        if not enabled():
            return
        human = state.human
        error = human.submit(data if isinstance(data, dict) else {}) if human is not None else 'No study is running.'
        if error:
            emit('human_helper_error', {'message': error})
