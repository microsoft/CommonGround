"""Headless command line for the AI-AI visual-information studies."""
import asyncio
from typing import Any, Dict

from .conditions import COMPLEXITY_LABELS, DEFAULT_FOV_COMPLEXITIES, StudyConfig
from .runner import StudyRunner

CREDENTIAL_HINT = ("Hint: AI modes need credentials. Set OPENAI_API_KEY (or run 'az login' for Entra ID) "
                   "and OPENAI_ENDPOINT/OPENAI_GPT4_DEPLOYMENT in .env.")


def describe(trial: Dict[str, Any]) -> str:
    """One-line description of a trial's condition from its ``TrialCondition.to_dict()``."""
    parts = [f"{COMPLEXITY_LABELS.get(trial['complexity'], trial['complexity'])} pieces"]
    if trial['experiment'] == 'rotation':
        parts.append(f"{trial['feedback']} feedback")
        if trial['alignment'] == 'rotated':
            transform = trial['transform']
            parts.append(f"rotated (flip {transform['flip']}, {transform['degrees']} deg)")
        else:
            parts.append('aligned views')
    else:
        parts.append(f"view {trial['fov_size']}")
        if trial['fov_control'] != 'n/a':
            parts.append(f"window control {trial['fov_control']}")
        if trial['alignment'] == 'rotated':
            transform = trial['transform']
            parts.append(f"rotated (flip {transform['flip']}, {transform['degrees']} deg)")
    return ', '.join(parts)


def _printer(event: Dict[str, Any]) -> None:
    kind = event['type']
    if kind == 'run_started':
        print(f"Run {event['run_id']}: {len(event['trials'])} trials, up to {event['max_turns']} Worker turns each, "
              f"model {event['model']}")
    elif kind == 'trial_started':
        trial = event['trial']
        print(f"\n=== Trial {event['index']}/{event['total']} (block {trial['block']}): {describe(trial)} ===")
    elif kind == 'message':
        print(f"{event['sender'].upper()}: {event['text']}")
    elif kind == 'action_result':
        if event['action'].get('action') == 'done':
            print(f"  [helper DONE] {event['detail']}")
        else:
            print(f"  [{event['role']} action] {'OK' if event['ok'] else 'REJECTED'}: {event['detail']}")
    elif kind == 'error':
        print(f"  [model error] {event['message']}")
    elif kind == 'trial_finished':
        result = event['result']
        looks = f" + {result['helper_looks']} looks" if result.get('helper_looks') else ''
        print(f"--- {'SOLVED' if result['solved'] else 'NOT solved'} in {result['turns']} turns{looks}, "
              f"{result['elapsed_s']:.1f}s ---")
    elif kind == 'run_finished':
        print(f"\n==== {event['status']}: {event['trials_solved']}/{event['trials_completed']} trials solved "
              f"({event['trials_total']} scheduled) ====")


def run_headless(args) -> int:
    """Run one agent pair through a study schedule; returns a process exit code."""
    config = StudyConfig(
        experiment=args.study, seed=args.seed, complexity=args.complexity, fov_control=args.fov_control,
        trials_per_block=args.trials_per_block, disclose_view_differences=not args.no_disclose,
        complexities=tuple(getattr(args, 'piece_sets', None) or DEFAULT_FOV_COMPLEXITIES),
        fov_alignment=getattr(args, 'fov_alignment', None) or 'aligned')
    try:
        from .agents import create_agents
        worker, helper = create_agents()
    except Exception as exc:
        print(f"[error] {type(exc).__name__}: {exc}\n{CREDENTIAL_HINT}")
        return 1
    runner = StudyRunner(config, worker, helper, max_turns=args.max_turns, trial_limit=args.limit, emit=_printer)
    print(f"Logs: {runner.run_dir}")
    summary = asyncio.run(runner.run())
    if summary['reason']:
        print(f"Reason: {summary['reason']}")
    return 0 if summary['status'] == 'completed' else 1
