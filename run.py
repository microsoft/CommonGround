"""
CommonGround puzzle — unified launcher.

Modes:
  human-ai     Web app: one human + one AI agent.
                 --role worker  -> human Worker + AI Helper (default)
                 --role helper  -> AI Worker + human Helper
  human-human  Web app: two humans in two browsers (paired via a shared link).
  ai-ai        Headless: an AI Helper guides an AI Worker (no browser).
                 --study rotation|field-of-view runs a visual-information study.
  observe      Web app: watch and control visual-information studies live
                 (AI Helper, or a human Helper at /study/helper).

Examples:
  python run.py human-ai
  python run.py human-ai --role helper --no-shared-view
  python run.py human-human
  python run.py ai-ai --limit 1
  python run.py ai-ai --study rotation --complexity patterned --limit 2
  python run.py ai-ai --study field-of-view --fov-control auto --piece-sets solid,figure
  python run.py ai-ai --study field-of-view --fov-control helper --piece-sets figure --fov-alignment rotated
  python run.py observe
"""
import argparse
import sys
import uuid

PIECE_SETS = ('solid', 'patterned', 'figure')


def _piece_sets(text):
    """Parse a comma-separated list of piece sets, e.g. 'solid,figure'."""
    names = [name.strip() for name in text.split(',') if name.strip()]
    unknown = [name for name in names if name not in PIECE_SETS]
    if not names or unknown:
        raise argparse.ArgumentTypeError(f"expected a comma-separated list of {', '.join(PIECE_SETS)}")
    if len(set(names)) != len(names):
        raise argparse.ArgumentTypeError("piece sets must not repeat")
    return names


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
    p_aa.add_argument('--limit', type=int, default=None,
                      help='Only run the first N puzzles (or trials, with --study)')
    p_aa.add_argument('--max-turns', type=int, default=20, help='Max worker turns per puzzle or trial')
    p_aa.add_argument('--study', choices=['rotation', 'field-of-view'], default=None,
                      help='Run a visual-information study instead of the configured puzzles')
    p_aa.add_argument('--complexity', choices=PIECE_SETS, default=None,
                      help='Piece set for the rotation study (between-pair factor); '
                           'figure = a circle with a stem, cut into cells')
    p_aa.add_argument('--piece-sets', type=_piece_sets, default=None,
                      help='Field-of-view study: comma-separated piece sets crossed with the view sizes '
                           'within a pair (default solid,patterned, as in the paper)')
    p_aa.add_argument('--fov-control', choices=['auto', 'worker', 'helper'], default=None,
                      help='Who controls the Helper window in the field-of-view study (between-pair factor)')
    p_aa.add_argument('--fov-alignment', choices=['aligned', 'rotated'], default=None,
                      help="Field-of-view study: the Helper's views aligned (default) or, in every trial, "
                           "mirrored horizontally and turned 90 degrees (between-pair factor)")
    p_aa.add_argument('--seed', type=int, default=0, help='Seed for the study schedule (default 0)')
    p_aa.add_argument('--trials-per-block', type=int, default=None,
                      help="Trials per block (paper: rotation 6, field of view 4)")
    p_aa.add_argument('--no-disclose', action='store_true',
                      help="Rotation study: do not tell the agents whether their views are rotated")

    p_obs = sub.add_parser('observe', help='Web app: watch AI-AI visual-information studies live')
    p_obs.add_argument('--port', type=int, default=None, help='Port (default 5000)')
    p_obs.add_argument('--host', default=None, help='Host to bind (default 127.0.0.1)')

    args = parser.parse_args()

    if args.mode == 'ai-ai':
        study_only = {'--complexity': args.complexity, '--fov-control': args.fov_control,
                      '--fov-alignment': args.fov_alignment, '--piece-sets': args.piece_sets,
                      '--trials-per-block': args.trials_per_block, '--no-disclose': args.no_disclose or None,
                      '--seed': args.seed or None}
        if not args.study:
            given = [flag for flag, value in study_only.items() if value is not None]
            if given:
                parser.error(f"{', '.join(given)} only apply with --study")
            import asyncio
            import ai_vs_ai
            asyncio.run(ai_vs_ai.main_async(
                argparse.Namespace(limit=args.limit, max_turns=args.max_turns)))
            return
        args.study = args.study.replace('-', '_')
        if args.study == 'rotation' and not args.complexity:
            parser.error("--study rotation needs --complexity solid|patterned|figure")
        if args.study == 'field_of_view' and not args.fov_control:
            parser.error("--study field-of-view needs --fov-control auto|worker|helper")
        if args.study == 'rotation' and args.fov_control:
            parser.error("--fov-control only applies to --study field-of-view")
        if args.study == 'rotation' and args.fov_alignment:
            parser.error("--fov-alignment only applies to --study field-of-view")
        if args.study == 'rotation' and args.piece_sets:
            parser.error("--piece-sets only applies to --study field-of-view; use --complexity for rotation")
        if args.study == 'field_of_view' and args.complexity:
            parser.error("--complexity only applies to --study rotation (the field-of-view study varies the "
                         "piece set within a pair; choose them with --piece-sets)")
        from studies.cli import run_headless
        code = run_headless(args)
        if code:
            sys.exit(code)
        return

    # Web modes
    from web_app import run_server
    port = args.port or 5000

    if args.mode == 'observe':
        run_server(mode=None, shared_view=True, run_study=False, host=args.host, port=port, observer=True)
        return

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
