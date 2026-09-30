"""Command-line interface for running and maintaining the grading app."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from typing import Sequence


def _print_problems(title: str, problems: Sequence[str]) -> None:
    if not problems:
        print(f"[OK] {title}")
        return
    print(f"[FAIL] {title}")
    for problem in problems:
        print(f"  - {problem}")


def _matrix_problems() -> tuple[list[str], dict[tuple[str, str], int]]:
    from .settings import settings

    problems: list[str] = []
    counts: Counter[tuple[str, str]] = Counter()
    matrix = settings.SNAPSHOT_MATRIX_CSV
    if not matrix.is_file():
        return [f"Missing snapshot matrix: {matrix}"], {}

    with matrix.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return [f"Snapshot matrix is empty: {matrix}"], {}

    for row in rows:
        condition = row.get("condition", "")
        version = row.get("condition_version", "")
        counts[(condition, version)] += 1
        snapshot_id = row.get("snapshot_id", "")
        snapshot = settings.SNAPSHOTS_DIR / f"{snapshot_id}.json"
        if not snapshot.is_file():
            problems.append(f"Missing snapshot: {snapshot}")
            continue
        try:
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"Unreadable snapshot {snapshot}: {error}")
            continue
        if payload.get("condition_version") != version:
            problems.append(
                f"Version mismatch in {snapshot.name}: "
                f"{payload.get('condition_version')!r} != {version!r}"
            )
        for board_field in ("target_board_image", "worker_board_image"):
            board_name = payload.get(board_field)
            if not board_name or not (settings.BOARDS_DIR / board_name).is_file():
                problems.append(
                    f"Missing {board_field} for {snapshot.name}: {board_name!r}"
                )
        if len(problems) >= 10:
            problems.append("Additional snapshot problems omitted")
            break
    expected = {
        (condition, settings.CONDITION_VERSIONS[condition])
        for condition in settings.CONDITIONS
    }
    if set(counts) != expected:
        problems.append(
            f"Matrix condition/version pairs are {sorted(counts)}, expected {sorted(expected)}"
        )
    return problems, dict(counts)


def _roster_problems() -> tuple[list[str], int]:
    from .assignment import ROSTER_CSV, _view_by_session
    from .settings import settings

    if not ROSTER_CSV.is_file():
        return [f"Missing participant roster: {ROSTER_CSV}"], 0
    with ROSTER_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    problems: list[str] = []
    required = {
        "participant_id", "credentials", "row_index", "dialogue_id",
        "view", "condition", "arm", "dialogues",
    }
    fields = set(rows[0]) if rows else set()
    if not rows:
        problems.append(f"Participant roster is empty: {ROSTER_CSV}")
    elif missing := required - fields:
        problems.append(f"Participant roster is missing columns: {sorted(missing)}")

    credentials = [row.get("credentials", "").strip() for row in rows]
    credentials = [value for value in credentials if value]
    if len(credentials) != len(set(credentials)):
        problems.append("Participant roster contains duplicate credentials")

    participant_ids = [row.get("participant_id", "").strip() for row in rows]
    participant_ids = [value for value in participant_ids if value]
    if len(participant_ids) != len(set(participant_ids)):
        problems.append("Participant roster contains duplicate participant IDs")

    built_dialogues = set(_view_by_session())
    for row_number, row in enumerate(rows, start=2):
        condition = row.get("condition", "").strip()
        if condition.lower() == "admin":
            continue
        if condition not in settings.CONDITIONS:
            problems.append(f"Roster row {row_number} has invalid condition {condition!r}")
        arm = row.get("arm", "").strip()
        if arm not in settings.ARMS:
            problems.append(f"Roster row {row_number} has invalid arm {arm!r}")
        credential = row.get("credentials", "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", credential):
            problems.append(f"Roster row {row_number} has a malformed credential")
        dialogue_text = row.get("dialogues", "").strip()
        dialogues = [value for value in dialogue_text.split(";") if value]
        if not dialogues:
            dialogue = row.get("dialogue_id", "").strip()
            dialogues = [dialogue] if dialogue else []
        unknown = set(dialogues) - built_dialogues
        if unknown:
            problems.append(
                f"Roster row {row_number} references unbuilt dialogues: {sorted(unknown)}"
            )
        if len(problems) >= 10:
            problems.append("Additional roster problems omitted")
            break
    return problems, len(rows)


def doctor(production: bool = False) -> int:
    """Check package data, generated artifacts, roster integrity, and security."""
    from .settings import settings

    runtime = settings.runtime_problems()
    matrix, counts = _matrix_problems()
    roster, roster_count = _roster_problems()
    production_issues = settings.production_problems() if production else []

    _print_problems("runtime artifacts", runtime)
    _print_problems("snapshot matrix", matrix)
    _print_problems("participant roster", roster)
    if production:
        _print_problems("production security", production_issues)

    if counts:
        summary = ", ".join(
            f"{condition}/{version}={count}"
            for (condition, version), count in sorted(counts.items())
        )
        print(f"Matrix: {summary}")
    print(f"Roster rows: {roster_count}")
    return int(bool(runtime or matrix or roster or production_issues))


def serve(host: str | None, port: int | None, production: bool) -> int:
    from .app import create_app
    from .settings import settings

    if production:
        problems = settings.runtime_problems() + settings.production_problems()
        if problems:
            _print_problems("production startup", problems)
            return 1
        from waitress import serve as waitress_serve

        app = create_app()
        listen_host = host or settings.HOST
        listen_port = port or settings.PORT
        print(f"Serving production app at http://{listen_host}:{listen_port}")
        waitress_serve(app, host=listen_host, port=listen_port)
        return 0

    app = create_app({
        "DEBUG": True,
        "HSTS_ENABLED": False,
        "SESSION_COOKIE_SECURE": False,
        "TRUST_PROXY_PROTO": False,
    })
    listen_host = host or "127.0.0.1"
    listen_port = port or settings.PORT
    print(f"Serving local app at http://{listen_host}:{listen_port}")
    app.run(host=listen_host, port=listen_port, debug=True, use_reloader=False)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uncertainty-grading",
        description="Run and maintain the standalone uncertainty grading study.",
    )
    subcommands = parser.add_subparsers(dest="command")

    serve_parser = subcommands.add_parser("serve", help="Run the web app")
    serve_parser.add_argument("--host")
    serve_parser.add_argument("--port", type=int)
    serve_parser.add_argument(
        "--production",
        action="store_true",
        help="Use Waitress and enforce production security settings",
    )

    doctor_parser = subcommands.add_parser("doctor", help="Validate the installation")
    doctor_parser.add_argument(
        "--production",
        action="store_true",
        help="Also enforce production security settings",
    )

    subcommands.add_parser("credentials", help="Generate participant credentials")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["serve"]
    if arguments[0] == "credentials":
        from .make_credentials import main as credentials_main

        return credentials_main(arguments[1:])
    args = _parser().parse_args(arguments)

    if args.command == "serve":
        return serve(args.host, args.port, args.production)
    if args.command == "doctor":
        return doctor(args.production)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())