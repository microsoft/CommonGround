"""
Headless AI vs AI runner for the puzzle collaboration task.

An LLM Helper guides an LLM Worker through the puzzles in utils/puzzles.json.
The full transcript is printed and logged to logs/ (session JSONL + trial_summary.csv),
so no browser or human is needed. Requires AI credentials (see .env.example).

Usage:
    python ai_vs_ai.py                 # run all puzzles
    python ai_vs_ai.py --limit 1       # only the first puzzle
    python ai_vs_ai.py --max-turns 15  # cap Worker turns per puzzle
"""
import argparse
import asyncio
import time
import uuid

from utils import settings
from game_session import GameSession


def _apply_worker_actions(game_session, actions):
    """Apply parsed Worker actions to the board; return list of (ok, message)."""
    results = []
    for action in actions or []:
        kind = action.get('action')
        if kind == 'place':
            x, y = action['position']
            results.append(game_session.place_piece(action['piece'], x, y))
        elif kind == 'move':
            fx, fy = action['from']
            tx, ty = action['to']
            results.append(game_session.move_piece(fx, fy, tx, ty))
        elif kind == 'remove':
            x, y = action['position']
            results.append(game_session.remove_piece(x, y))
    return results


def _solved(game_session):
    """True when the worker's board exactly matches the target."""
    return game_session.work_area == game_session.target_area


async def run_puzzle(game_session, puzzle_index, max_turns):
    num_pieces, puzzle = game_session.start_trial(puzzle_index)
    print(
        f"\n=== Puzzle {puzzle['puzzle_number']} "
        f"({puzzle.get('group', '')}, {puzzle.get('condition', '')}) — "
        f"{num_pieces} pieces, shared_view={game_session.shared_view} ==="
    )
    start = time.time()

    helper_msg = await game_session.get_llm_helper_response(None)
    if helper_msg:
        game_session.add_message('helper', helper_msg)
        print(f"HELPER: {helper_msg}")

    solved = False
    turn = 0
    for turn in range(1, max_turns + 1):
        worker_res = await game_session.get_llm_worker_action()
        if not worker_res:
            print("  [worker] no response (LLM error?) — skipping turn")
        else:
            for ok, msg in _apply_worker_actions(game_session, worker_res.get('actions')):
                print(f"  [worker action] {'OK' if ok else 'REJECTED'}: {msg}")
            if worker_res.get('message'):
                game_session.add_message('worker', worker_res['message'])
                print(f"WORKER: {worker_res['message']}")

        if _solved(game_session):
            solved = True
            break

        helper_msg = await game_session.get_llm_helper_response(None)
        if helper_msg:
            game_session.add_message('helper', helper_msg)
            print(f"HELPER: {helper_msg}")

    elapsed = time.time() - start
    if game_session.agent_controller:
        game_session.agent_controller.end_trial(solved, elapsed)
    print(
        f"--- Puzzle {puzzle['puzzle_number']}: "
        f"{'SOLVED' if solved else 'NOT solved'} in {turn} turns, {elapsed:.1f}s ---"
    )
    return solved


async def main_async(args):
    # Ensure the Helper responds on every Worker turn (disable proactive gating).
    settings.HELPER_GUIDANCE_FREQUENCY = 1

    session_id = f"ai_ai_{uuid.uuid4().hex[:8]}"
    game_session = GameSession(session_id, worker_mode='llm', helper_mode='llm')
    if game_session.session_logger:
        game_session.session_logger.start_session(
            session_id, user_id='ai_ai', role='ai_ai',
            config={'worker_mode': 'llm', 'helper_mode': 'llm'},
        )

    total = len(game_session.puzzles)
    if not total:
        print("No puzzles found in utils/puzzles.json")
        return
    count = total if args.limit is None else min(args.limit, total)

    solved_count = 0
    for i in range(count):
        solved_count += int(await run_puzzle(game_session, i, args.max_turns))

    print(f"\n==== Done: {solved_count}/{count} puzzles solved ====")


def main():
    parser = argparse.ArgumentParser(description="Headless AI vs AI puzzle runner")
    parser.add_argument('--limit', type=int, default=None, help='Only run the first N puzzles')
    parser.add_argument('--max-turns', type=int, default=20, help='Max Worker turns per puzzle')
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except Exception as e:  # noqa: BLE001 - surface a friendly hint for the common case
        print(f"\n[error] {type(e).__name__}: {e}")
        print("Hint: AI modes need credentials. Set OPENAI_API_KEY (or run 'az login' "
              "for Entra ID) and OPENAI_ENDPOINT/OPENAI_GPT4_DEPLOYMENT in .env.")
        raise


if __name__ == '__main__':
    main()
