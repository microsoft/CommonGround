"""Participant assignment for Study 4.

Study-mode assignment is **deliberate and roster-driven**: ``data/participant_roster.csv``
is the single source of truth. Each row maps a participant's **credential** to a
fixed condition (A/B/C/D/E), rating type (``arm`` CB/CA), session (``dialogue_id``)
and view. ``row_for_credentials`` reads that row directly; the per-session
rating points (W1..Wn = ``trials``) come from the built
``stimuli/snapshot_matrix.csv``.
Local mode selects a condition, rating type, and dialogue without using a roster.
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


def _snapshot_types_by_session(
    condition: str | None = None, arm: str | None = None,
) -> Dict[str, List[str]]:
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
            if condition is not None and rec.get("condition") != condition:
                continue
            if arm is not None and rec.get("arm") != arm:
                continue
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
    snapshot_types = _snapshot_types_by_session(condition, arm).get(dialogue_id, [])
    return [{
        "trial_index": i,
        "dialogue_id": dialogue_id,
        "condition": condition,
        "snapshot_type": snapshot_type,
        "arm": arm,
    } for i, snapshot_type in enumerate(snapshot_types)]


def local_assignment(
    condition: str = "A", arm: str = "CA",
    dialogue_id: str | None = None, view: str = "source",
) -> Dict:
    """Choose one local dialogue without reading or modifying a participant roster."""
    if condition not in S.CONDITIONS or arm not in S.ARMS:
        raise ValueError(f"Unknown grading condition or arm: {condition}/{arm}")
    if view not in ("source", "shared", "nonshared"):
        raise ValueError(f"Unknown local view: {view}")
    available = _snapshot_types_by_session(condition, arm)
    if not available:
        raise ValueError(
            f"No {condition}/{arm} rating points found in {S.SNAPSHOT_MATRIX_CSV}. "
            "Restore matching local stimulus files before starting."
        )
    dialogue_id = dialogue_id if dialogue_id is not None else next(iter(available))
    if dialogue_id not in available:
        raise ValueError(f"Dialogue {dialogue_id!r} has no {condition}/{arm} rating points.")
    source_view = _view_by_session()[dialogue_id]
    presented_view = source_view if view == "source" else view
    if presented_view not in ("shared", "nonshared"):
        raise ValueError(
            f"Dialogue {dialogue_id!r} has no valid source view; use --view shared or nonshared."
        )
    trials = _trials_for(condition, arm, dialogue_id)
    for trial in trials:
        snapshot = S.SNAPSHOTS_DIR / (
            f"{dialogue_id}_{condition}_{trial['snapshot_type']}_{arm}.json"
        )
        if not snapshot.is_file():
            raise ValueError(f"Missing local snapshot: {snapshot}. Restore matching stimulus files.")
    return {
        "row_index": None,
        "condition": condition,
        "arm": arm,
        "dialogue_id": dialogue_id,
        "dialogues": [dialogue_id],
        "view": presented_view,
        "source_view": source_view,
        "trials": trials,
    }


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
