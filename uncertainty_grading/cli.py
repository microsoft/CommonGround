"""Command-line interface for local grading and optional participant studies."""
from __future__ import annotations

import argparse
import sys
from typing import Sequence


def _print_problems(title: str, problems: Sequence[str]) -> None:
    print(f"[FAIL] {title}")
    for problem in problems:
        print(f"  - {problem}")


def serve(
    host: str | None,
    port: int | None,
    production: bool,
    *,
    study: bool = False,
    condition: str = "A",
    arm: str = "CA",
    dialogue: str | None = None,
    view: str = "source",
) -> int:
    from .app import create_app
    from .assignment import local_assignment
    from .settings import settings

    problems = settings.runtime_problems()
    if production:
        problems += settings.production_problems()
    if problems:
        _print_problems("Cannot start grading", problems)
        return 1

    if production:
        from waitress import serve as waitress_serve

        app = create_app()
        listen_host = host or settings.HOST
        listen_port = port or settings.PORT
        print(f"Serving study app at http://{listen_host}:{listen_port}")
        waitress_serve(app, host=listen_host, port=listen_port)
        return 0

    local = None
    if not study:
        try:
            local = local_assignment(condition, arm, dialogue, view)
        except (OSError, ValueError) as error:
            _print_problems("Cannot start local grading", [str(error)])
            return 1

    app = create_app({
        "DEBUG": False,
        "HSTS_ENABLED": False,
        "SESSION_COOKIE_SECURE": False,
        "TRUST_PROXY_PROTO": False,
        "LOCAL_ASSIGNMENT": local,
    })
    listen_host = host or "127.0.0.1"
    listen_port = port or settings.PORT
    mode = "study (login required)" if study else f"local ({condition}/{arm}, no login)"
    print(f"Serving {mode} grading at http://{listen_host}:{listen_port}")
    app.run(
        host=listen_host, port=listen_port,
        debug=False, use_debugger=False, use_reloader=False,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run uncertainty grading locally, or use --study for participant login.",
    )
    subcommands = parser.add_subparsers(dest="command")

    serve_parser = subcommands.add_parser(
        "serve",
        help="Run the web app (the default command)",
        description="Start local grading without credentials. Use --study to require login.",
        epilog="Examples: python run.py; python run.py --study; "
               "python run.py credentials --help",
    )
    serve_parser.add_argument("--host")
    serve_parser.add_argument("--port", type=int)
    serve_parser.add_argument("--study", action="store_true",
                              help="Use the participant roster and access-code login")
    serve_parser.add_argument("--condition", choices=("A", "B", "C", "D", "E"),
                              help="Local grading condition (default: A)")
    serve_parser.add_argument("--arm", choices=("CB", "CA"),
                              help="Local rating type (default: CA)")
    serve_parser.add_argument("--dialogue",
                              help="Local dialogue ID (default: first in the matching matrix rows)")
    serve_parser.add_argument("--view", choices=("source", "shared", "nonshared"),
                              help="Local board visibility (default: source)")
    serve_parser.add_argument(
        "--production",
        action="store_true",
        help="Use Waitress with study login and production security settings",
    )

    subcommands.add_parser("credentials", help="Generate optional study access codes")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0].startswith("-"):
        arguments.insert(0, "serve")
    if arguments[0] == "credentials":
        from .make_credentials import main as credentials_main

        return credentials_main(arguments[1:])
    parser = _parser()
    args = parser.parse_args(arguments)
    if args.command == "serve":
        local_options = (args.condition, args.arm, args.dialogue, args.view)
        if (args.study or args.production) and any(value is not None for value in local_options):
            parser.error("--condition, --arm, --dialogue, and --view are for local mode; "
                         "study assignments come from the roster")
        if args.port is not None and not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        return serve(
            args.host, args.port, args.production,
            study=args.study,
            condition=args.condition or "A",
            arm=args.arm or "CA",
            dialogue=args.dialogue,
            view=args.view or "source",
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
