r"""Generate Study 4 participant credentials + roster rows.

Assignment is deliberate and **roster-driven**: ``data/participant_roster.csv``
is the single source of truth (columns
``participant_id,credentials,row_index,dialogue_id,view,condition,arm``). At
login a participant is looked up **only by their credential**; condition / arm /
session / view all come from their roster row. This tool mints fresh random
credentials and adds roster rows for the condition(s), rating type(s) and
session(s) you choose. ``participant_id`` is a 6-digit hash of the credential.

Run from the standalone folder:

    # 3 participants in cell A / CA on two specific sessions
    python run.py credentials --condition A --arm CA \
        --dialogues 16c68e60,f488e002 --n 3

    # one participant per built non-shared session, cell C / CB
    python run.py credentials --condition C --arm CB --dialogues nonshared

    # full 2x2 cell grid, one participant per built session, PREVIEW only
    python run.py credentials --condition A,C --arm CB,CA \
        --dialogues all --dry-run

``--condition`` / ``--arm`` / ``--dialogues`` accept comma lists; ``--dialogues``
also accepts ``all`` | ``shared`` | ``nonshared``. View is derived automatically
from each session. With ``--dry-run`` nothing is written; otherwise the roster is
rewritten (in canonical column order) with the new rows added, and printed so you
can distribute the credentials.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import random
import secrets
from typing import Dict, List

from .assignment import load_roster, _view_by_session
from .settings import settings as S
from . import roster_archive

ROSTER_CSV = S.DATA_DIR / "participant_roster.csv"
FIELDS = ["participant_id", "credentials", "row_index", "dialogue_id",
          "view", "condition", "arm", "dialogues"]
CONDITIONS = set(S.CONDITIONS)
ARMS = set(S.ARMS)


def _resolve_dialogues(spec: str, views: Dict[str, str]) -> List[str]:
    """Turn a ``--dialogues`` spec into a concrete list of built dialogue_ids."""
    key = spec.strip().lower()
    if key == "all":
        return list(views)
    if key in ("shared", "nonshared"):
        return [d for d, v in views.items() if v == key]
    return [d.strip() for d in spec.split(",") if d.strip()]


def _next_row_index(roster: List[Dict]) -> int:
    """Next free row_index, ignoring rows explicitly marked as admin."""
    max_row = -1
    for r in roster:
        if (r.get("condition") or "").strip().lower() == "admin":
            continue
        ri = (r.get("row_index") or "").strip()
        if ri.isdigit():
            max_row = max(max_row, int(ri))
    return max_row + 1


def _hash_pid(cred: str, used: set) -> str:
    """A 6-digit participant id derived from the credential (kept collision-free)."""
    n = int(hashlib.sha256(cred.encode()).hexdigest(), 16) % 1_000_000
    while f"{n:06d}" in used:
        n = (n + 1) % 1_000_000
    pid = f"{n:06d}"
    used.add(pid)
    return pid


def _regular_pairs(n: int, k: int) -> List[tuple]:
    """A k-regular set of unordered index pairs on n nodes (each node in k pairs)."""
    edges = set()
    for off in range(1, k // 2 + 1):
        for i in range(n):
            a, b = i, (i + off) % n
            edges.add((min(a, b), max(a, b)))
    if k % 2 == 1:                      # antipodal 1-factor (requires even n)
        half = n // 2
        for i in range(half):
            edges.add((i, i + half))
    return sorted(edges)


def _counterbalanced_pairs(dialogues: List[str], k: int) -> List[tuple]:
    """Ordered (d1, d2) pairs, each dialogue in k pairs, first/second position balanced."""
    idx = _regular_pairs(len(dialogues), k)
    random.shuffle(idx)
    firsts: Dict[str, int] = {}
    out = []
    for a, b in idx:
        da, db = dialogues[a], dialogues[b]
        if firsts.get(da, 0) <= firsts.get(db, 0):
            out.append((da, db))
            firsts[da] = firsts.get(da, 0) + 1
        else:
            out.append((db, da))
            firsts[db] = firsts.get(db, 0) + 1
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate Study 4 participant credentials + roster rows.")
    ap.add_argument("--condition", required=True,
                    help="A/B/C/D/E (comma list). A=Baseline, "
                        "B=Baseline + candidates, C=Unambiguous Description, "
                        "D=Diagnostic Uncertainty, "
                        "E=Confidence-Triggered Uncertainty.")
    ap.add_argument("--arm", required=True,
                    help="CB and/or CA (comma list). CB=rate before the move, CA=after.")
    ap.add_argument("--dialogues", required=True,
                    help="all | shared | nonshared | comma list of dialogue_ids.")
    ap.add_argument("--view", choices=["shared", "nonshared", "source"], default="source",
                    help="Presented view (decoupled from the dialogue's source): "
                         "'shared' shows the Worker board, 'nonshared' hides it, "
                         "'source' (default) uses each dialogue's original group.")
    ap.add_argument("--n", type=int, default=1,
                    help="Participants per (session x condition x arm) cell (default 1). "
                         "In --pair mode this is the number of graders per dialogue.")
    ap.add_argument("--pair", action="store_true",
                    help="Multi-dialogue mode: give each participant a balanced, "
                         "order-counterbalanced PAIR of dialogues (both orders spread "
                         "across participants). Each dialogue appears in --n pairs.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the rows but do not modify the roster.")
    args = ap.parse_args(argv)

    conditions = [c.strip().upper() for c in args.condition.split(",") if c.strip()]
    arms = [a.strip().upper() for a in args.arm.split(",") if a.strip()]
    if not conditions or [c for c in conditions if c not in CONDITIONS]:
        ap.error(f"invalid --condition {conditions}; allowed: {sorted(CONDITIONS)}")
    if not arms or [a for a in arms if a not in ARMS]:
        ap.error(f"invalid --arm {arms}; allowed: CB, CA")
    if args.n < 1:
        ap.error("--n must be at least 1.")

    views = _view_by_session()
    if not views:
        ap.error(f"no dialogues found in {S.SNAPSHOT_MATRIX_CSV}; "
                 "restore the local snapshot matrix and matching stimulus files first.")
    dialogues = _resolve_dialogues(args.dialogues, views)
    unknown = [d for d in dialogues if d not in views]
    if unknown:
        ap.error(f"unknown dialogue_id(s) {unknown}; built sessions: {sorted(views)}")
    if not dialogues:
        ap.error("no dialogues selected.")

    if args.pair:
        n_d = len(dialogues)
        if n_d < 2:
            ap.error("--pair needs at least 2 dialogues in --dialogues.")
        if args.n >= n_d:
            ap.error(f"--n ({args.n}) must be < number of dialogues ({n_d}) in --pair mode.")
        if (n_d * args.n) % 2 != 0 or (args.n % 2 == 1 and n_d % 2 == 1):
            ap.error(f"--pair needs a feasible design: dialogues*n must be even and "
                     f"odd n needs an even dialogue count (dialogues={n_d}, n={args.n}).")

    roster = load_roster()
    existing_creds = {(r.get("credentials") or "").strip() for r in roster}
    used_pids = {(r.get("participant_id") or "").strip() for r in roster}
    row_i = _next_row_index(roster)

    def _mint(dialogue_id, dialogues_str, view, condition, arm):
        nonlocal row_i
        cred = secrets.token_hex(16)
        while cred in existing_creds:
            cred = secrets.token_hex(16)
        existing_creds.add(cred)
        row = {
            "participant_id": _hash_pid(cred, used_pids),
            "credentials": cred,
            "row_index": str(row_i),
            "dialogue_id": dialogue_id,
            "dialogues": dialogues_str,
            "view": view,
            "condition": condition,
            "arm": arm,
        }
        row_i += 1
        return row

    new_rows: List[Dict] = []
    if args.pair:
        pairs = _counterbalanced_pairs(dialogues, args.n)
        for condition in conditions:
            for arm in arms:
                for d1, d2 in pairs:
                    src = views[d1]
                    view = src if args.view == "source" else args.view
                    new_rows.append(_mint(d1, f"{d1};{d2}", view, condition, arm))
    else:
        for dialogue_id in dialogues:
            source_view = views[dialogue_id]
            view = source_view if args.view == "source" else args.view
            for condition in conditions:
                for arm in arms:
                    for _ in range(args.n):
                        new_rows.append(_mint(dialogue_id, "", view, condition, arm))

    dcol = 24 if args.pair else 11
    print(f"{'participant':<12}{'cond':<6}{'arm':<5}{'view':<11}{'dialogue(s)':<{dcol}}credentials")
    for r in new_rows:
        dshow = r.get("dialogues") or r["dialogue_id"]
        print(f"{r['participant_id']:<12}{r['condition']:<6}{r['arm']:<5}"
              f"{r['view']:<11}{dshow:<{dcol}}{r['credentials']}")
    print(f"\n{len(new_rows)} new participant(s).")
    if args.pair:
        from collections import Counter
        cells = len(conditions) * len(arms)
        cov = Counter(d for r in new_rows for d in r["dialogues"].split(";"))
        per = {d: c // cells for d, c in sorted(cov.items())}
        print(f"pair mode: {len(new_rows)} rows = {len(new_rows) // cells} pairs x {cells} "
              f"cell(s); graders/dialogue/cell min={min(per.values())} max={max(per.values())}")

    if args.dry_run:
        print("dry-run: roster NOT modified.")
        return 0

    snap = roster_archive.snapshot_roster("pre-generate")
    if snap:
        print(f"Archived previous roster -> {snap.name}")

    all_rows = list(roster) + new_rows
    with ROSTER_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print(f"Wrote {len(all_rows)} row(s) ({len(new_rows)} new) to {ROSTER_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
