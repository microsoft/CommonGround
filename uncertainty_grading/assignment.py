"""Participant assignment for Study 4.

Assignment is **deliberate and roster-driven**: ``data/participant_roster.csv``
is the single source of truth. Each row maps a participant's **credential** to a
fixed condition (A/B/C/D/E), rating type (``arm`` CB/CA), session (``dialogue_id``)
and view. ``row_for_credentials`` reads that row directly; the per-session
rating points (W1..Wn = ``trials``) come from the built
``stimuli/snapshot_matrix.csv``.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List

from .settings import settings as S


# --------------------------------------------------------------------------- #
# Session pool
# --------------------------------------------------------------------------- #
def _sessions_from_matrix() -> List[str]:
    """Distinct main session ids, in first-seen order, from the snapshot matrix."""
    seen: List[str] = []
    if not S.SNAPSHOT_MATRIX_CSV.exists():
        return seen
    with S.SNAPSHOT_MATRIX_CSV.open(encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            if rec["dialogue_id"] not in seen:
                seen.append(rec["dialogue_id"])
    return seen


def _snapshot_types_by_session() -> Dict[str, List[str]]:
    """``dialogue_id -> ordered [W1 .. Wn]`` rating points, from the matrix.

    The number of rateable Worker turns varies per session (the whole
    conversation of its trial 2 + trial 3), so the trajectory length is read
    from the built matrix rather than fixed in settings.
    """
    order: Dict[str, Dict[str, int]] = {}
    if not S.SNAPSHOT_MATRIX_CSV.exists():
        return {}
    with S.SNAPSHOT_MATRIX_CSV.open(encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            d = rec["dialogue_id"]
            st = rec["snapshot_type"]
            idx = int(rec.get("rating_point_index", 0))
            order.setdefault(d, {})[st] = idx
    return {d: [st for st, _ in sorted(sts.items(), key=lambda kv: kv[1])]
            for d, sts in order.items()}


def _view_by_session() -> Dict[str, str]:
    """``dialogue_id -> view`` ("shared"/"nonshared"), from the snapshot matrix."""
    views: Dict[str, str] = {}
    if not S.SNAPSHOT_MATRIX_CSV.exists():
        return views
    with S.SNAPSHOT_MATRIX_CSV.open(encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            views.setdefault(rec["dialogue_id"], rec.get("view", ""))
    return views


# --------------------------------------------------------------------------- #
# Row generation
# --------------------------------------------------------------------------- #
def _trials_for(condition: str, arm: str, dialogue_id: str) -> List[Dict]:
    """Every rating point (W1 .. Wn) of a session in one cell, in order."""
    snapshot_types = _snapshot_types_by_session().get(dialogue_id, [])
    return [{
        "trial_index": i,
        "dialogue_id": dialogue_id,
        "condition": condition,
        "snapshot_type": snapshot_type,
        "arm": arm,
    } for i, snapshot_type in enumerate(snapshot_types)]


# --------------------------------------------------------------------------- #
# Deliberate participant -> assignment roster (the single source of truth)
# --------------------------------------------------------------------------- #
ROSTER_CSV = S.DATA_DIR / "participant_roster.csv"


def load_roster() -> List[Dict]:
    """All participant rows from ``data/participant_roster.csv``.

    The roster is the single source of truth for deliberate assignment: each
    credential is mapped to a fixed condition / rating type (``arm``) / session
    (``dialogue_id``) / view. Columns: ``participant_id, row_index,
    dialogue_id, view, condition, arm, credentials``.
    """
    if not ROSTER_CSV.exists():
        return []
    with ROSTER_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def row_for_credentials(credentials: str) -> Dict | None:
    """Full assignment for a credential, read directly from the roster.

    Returns ``{row_index, condition, arm, dialogue_id, view, source_view,
    trials}`` or ``None`` if the credential is not in the roster. ``view`` is the
    PRESENTED view (roster column, defaulting to the source group) and controls
    whether the Worker board is shown; ``source_view`` is the dialogue's original
    group (provenance). ``trials`` (the W1..Wn rating points) are read from the
    built ``snapshot_matrix.csv`` for the assigned session.
    """
    cred = (credentials or "").strip()
    if not cred:
        return None
    row = next((r for r in load_roster()
                if (r.get("credentials") or "").strip() == cred), None)
    if row is None:
        return None
    condition = (row.get("condition") or "").strip()
    arm = (row.get("arm") or "").strip()
    # A participant may grade an ordered list of dialogues (';'-separated in the
    # 'dialogues' column, in grading order); legacy rows fall back to the single
    # 'dialogue_id'. 'dialogue_id' is kept as the first dialogue for display.
    dialogues = [d.strip() for d in (row.get("dialogues") or "").split(";") if d.strip()]
    if not dialogues:
        single = (row.get("dialogue_id") or "").strip()
        dialogues = [single] if single else []
    dialogue_id = dialogues[0] if dialogues else ""
    src_view = _view_by_session().get(dialogue_id, "")
    view = (row.get("view") or "").strip() or src_view
    row_index = (row.get("row_index") or "").strip()
    trials: List[Dict] = []
    for d in dialogues:
        trials.extend(_trials_for(condition, arm, d))
    return {
        "row_index": int(row_index) if row_index else None,
        "condition": condition,
        "arm": arm,
        "dialogue_id": dialogue_id,
        "dialogues": dialogues,
        "view": view,
        "source_view": src_view,
        "trials": trials,
        "is_admin": condition.lower() == "admin",
    }


if __name__ == "__main__":
    roster = [r for r in load_roster()
              if (r.get("credentials") or "").strip()
              and (r.get("condition") or "").strip().lower() != "admin"]
    cells = sorted({(r["condition"], r["arm"]) for r in roster})
    sessions = sorted({r["dialogue_id"] for r in roster})
    missing = [r["participant_id"] for r in roster
               if not (row_for_credentials(r["credentials"]) or {}).get("trials")]
    print(f"Roster: {len(roster)} participants, {len(cells)} cells, "
          f"{len(sessions)} sessions.")
    print("All participants resolve to built trials."
          if not missing else
          f"WARNING: no built trials for {len(missing)}: {missing}")
