"""
CommonGround puzzle — unified launcher.

Modes:
  human-ai     Web app: one human + one AI agent.
                 --role worker  -> human Worker + AI Helper (default)
                 --role helper  -> AI Worker + human Helper
  human-human  Web app: two humans in two browsers (paired via a shared link).
  ai-ai        Headless: an AI Helper guides an AI Worker (no browser).

Examples:
  python run.py human-ai
  python run.py human-ai --role helper --no-shared-view
  python run.py human-human
  python run.py ai-ai --limit 1
"""
import argparse
import uuid


def _add_web_opts(p):
    p.add_argument('--port', type=int, default=None, help='Port (default 5000)')
    p.add_argument('--no-shared-view', action='store_true',
                   help='Helper cannot see the worker board in real time')
    p.add_argument('--study', action='store_true', help='Study mode (requires login)')


def main():
    parser = argparse.ArgumentParser(
        description="Run the CommonGround puzzle in human-AI, human-human, or AI-AI mode.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest='mode', required=True)

    p_hai = sub.add_parser('human-ai', help='Web app: one human + one AI agent')
    p_hai.add_argument('--role', choices=['worker', 'helper'], default='worker',
                       help='Which role the human plays (default: worker -> AI is helper)')
    _add_web_opts(p_hai)

    p_hh = sub.add_parser('human-human', help='Web app: two humans (shared link)')
    _add_web_opts(p_hh)

    p_aa = sub.add_parser('ai-ai', help='Headless: AI helper guides AI worker')
    p_aa.add_argument('--limit', type=int, default=None, help='Only run the first N puzzles')
    p_aa.add_argument('--max-turns', type=int, default=20, help='Max worker turns per puzzle')

    args = parser.parse_args()

    if args.mode == 'ai-ai':
        import asyncio
        import ai_vs_ai
        asyncio.run(ai_vs_ai.main_async(
            argparse.Namespace(limit=args.limit, max_turns=args.max_turns)))
        return

    # Web modes
    from web_app import run_server
    port = args.port or 5000
    shared_view = not args.no_shared_view

    if args.mode == 'human-ai':
        mode = args.role  # 'worker' = human worker + AI helper; 'helper' = AI worker + human helper
        human = 'Worker' if args.role == 'worker' else 'Helper'
        ai = 'Helper' if args.role == 'worker' else 'Worker'
        print(f"Human {human} + AI {ai}. Open http://localhost:{port}")
    else:  # human-human
        mode = None
        room = uuid.uuid4().hex[:8]
        q = f"session={room}&auto_worker=human&auto_helper=human"
        print("Human-human: send each player one of these links (same room id):")
        print(f"  Worker: http://localhost:{port}/worker?{q}")
        print(f"  Helper: http://localhost:{port}/helper?{q}")

    run_server(mode=mode, shared_view=shared_view, run_study=args.study, port=port)


if __name__ == '__main__':
    main()
