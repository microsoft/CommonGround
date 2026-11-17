"""Persistence for Study 4: stimulus loading, per-participant JSONL event logs,
and the long-format processed CSV export used for analysis.

No database — responses are appended as JSON lines under ``data/raw/`` (one
file per participant, gitignored) and flattened to ``data/processed/`` on
export, matching the layout in §14 of the design summary.
"""
from __future__ import annotations

import csv
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from werkzeug.utils import secure_filename

from .settings import settings as S

_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_GRADINGS_LOCK = threading.Lock()  # Shared lock for gradings file


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock_for(participant_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        if participant_id not in _LOCKS:
            _LOCKS[participant_id] = threading.Lock()
        return _LOCKS[participant_id]


# --------------------------------------------------------------------------- #
# Stimulus loading
# --------------------------------------------------------------------------- #
def snapshot_path(dialogue_id: str, condition: str, snapshot_type: str, arm: str) -> Path:
    return S.SNAPSHOTS_DIR / f"{dialogue_id}_{condition}_{snapshot_type}_{arm}.json"


def load_snapshot(dialogue_id: str, condition: str, snapshot_type: str, arm: str) -> Optional[Dict]:
    path = snapshot_path(dialogue_id, condition, snapshot_type, arm)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_snapshot_by_id(snapshot_id: str) -> Optional[Dict]:
    path = S.SNAPSHOTS_DIR / f"{snapshot_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_snapshot_ids() -> List[str]:
    return sorted(p.stem for p in S.SNAPSHOTS_DIR.glob("*.json"))


# --------------------------------------------------------------------------- #
# Per-participant JSONL event log
# --------------------------------------------------------------------------- #
def _log_file(directory: Path, prefix: str, identifier: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
        raise ValueError("Log identifiers must contain only ASCII letters, digits, '-' or '_'.")
    filename = secure_filename(f"{prefix}_{identifier}.jsonl")
    return directory / filename


def _participant_file(participant_id: str) -> Path:
    return _log_file(S.RAW_DIR, "participant", participant_id)


def _grading_file(credentials: str) -> Path:
    return _log_file(S.GRADINGS_DIR, "grading", credentials)


def log_event(participant_id: str, event_type: str, data: Optional[Dict] = None,
              arm: Optional[str] = None) -> None:
    """Append one event line to the participant's JSONL log."""
    record = {
        "timestamp": _now(),
        "study_id": S.STUDY_ID,
        "participant_id": participant_id,
        "arm": arm,
        "event_type": event_type,
        "data": data or {},
    }
    path = _participant_file(participant_id)
    with _lock_for(participant_id):
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def read_events(participant_id: str) -> List[Dict]:
    path = _participant_file(participant_id)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --------------------------------------------------------------------------- #
# Gradings log (JSONL)
# --------------------------------------------------------------------------- #
def log_grading(credentials: str, participant_id: str, dialogue_id: str, 
                condition: str, view: str, turn: str, grade: int, 
                rt_ms: int, arm: Optional[str] = None,
                condition_version: Optional[str] = None,
                next_action: Optional[str] = None,
                worker_confidence: Optional[int] = None,
                source_view: Optional[str] = None,
                is_check: bool = False) -> None:
    """Append one grading record to the gradings JSONL file.
    
    Args:
        credentials: Participant's credential code
        participant_id: Prolific ID or participant identifier
        dialogue_id: Session identifier
        condition: A, B, C, D, or E
        view: shared or nonshared
        turn: Snapshot type (W1, W2, etc.) or P1W1 for practice
        grade: Rating value (0-100)
        rt_ms: Response time in milliseconds
        arm: CB or CA
    """
    gradings_file = _grading_file(credentials)
    record = {
        "timestamp": _now(),
        "credentials": credentials,
        "participant_id": participant_id,
        "dialogue_id": dialogue_id,
        "condition": condition,
        "condition_version": condition_version,
        "view": view,
        "source_view": source_view,
        "turn": turn,
        "grade": grade,
        "worker_confidence": worker_confidence,
        "next_action": next_action,
        "rt_ms": rt_ms,
        "arm": arm,
        "is_check": is_check,
    }
    with _GRADINGS_LOCK:
        with gradings_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def read_gradings() -> List[Dict]:
    """Read all gradings from per-participant JSONL files."""
    rows: List[Dict] = []
    for gradings_file in sorted(S.GRADINGS_DIR.glob("grading_*.jsonl")):
        with gradings_file.open(encoding="utf-8") as f:
            rows.extend(json.loads(line) for line in f if line.strip())
    return rows

EXPORT_FIELDS = [
    "participant_id", "arm", "trial_index", "dialogue_id", "condition", "condition_version",
    "snapshot_type", "puzzle_number", "shared_view", "view", "source_view", "word_count",
    "ground_truth_piece", "placed_piece", "worker_correct",
    "rating", "worker_confidence", "next_action", "rt_ms",
    "is_practice", "is_check", "familiarity",
    "ai_trust", "ai_understand", "ai_detect_uncertainty",
    "pair_same_page", "pair_ai_understood", "pair_smooth", "pair_repeated",
    "attention_passed", "submitted_at",
]


def export_long_csv(out_path: Optional[Path] = None) -> Path:
    """Flatten all participants' rating events into one long-format CSV.

    One row per main-trial rating. Post-task fields (familiarity, AI experience,
    pair impressions, and attention) are merged onto the participant's rows.
    """
    out_path = out_path or (
        S.EXPORTS_DIR / f"study4_long_{datetime.now():%Y%m%d_%H%M%S}.csv"
    )
    rows: List[Dict] = []

    for jsonl in sorted(S.RAW_DIR.glob("participant_*.jsonl")):
        events = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not events:
            continue
        pid = events[0]["participant_id"]
        arm = next((e["arm"] for e in events if e.get("arm")), None)

        # Participant-level post-task aggregates.
        familiarity = None
        survey_ratings = {
            "ai_trust": None,
            "ai_understand": None,
            "ai_detect_uncertainty": None,
            "pair_same_page": None,
            "pair_ai_understood": None,
            "pair_smooth": None,
            "pair_repeated": None,
        }
        attention_passed = None

        for e in events:
            d = e.get("data", {})
            if e["event_type"] == "familiarity_submitted":
                familiarity = d.get("value")
                for field in survey_ratings:
                    survey_ratings[field] = d.get(field)
            elif e["event_type"] == "attention_check":
                attention_passed = d.get("passed")

        for e in events:
            if e["event_type"] != "rating_submitted":
                continue
            d = e["data"]
            snap_id = d.get("snapshot_id")
            rows.append({
                "participant_id": pid,
                "arm": arm,
                "trial_index": d.get("trial_index"),
                "dialogue_id": d.get("dialogue_id"),
                "condition": d.get("condition"),
                "condition_version": d.get("condition_version"),
                "snapshot_type": d.get("snapshot_type"),
                "puzzle_number": d.get("puzzle_number"),
                "shared_view": d.get("shared_view"),
                "view": d.get("view"),
                "source_view": d.get("source_view"),
                "word_count": d.get("word_count"),
                "ground_truth_piece": d.get("ground_truth_piece"),
                "placed_piece": d.get("placed_piece"),
                "worker_correct": d.get("worker_correct"),
                "rating": d.get("rating"),
                "worker_confidence": d.get("worker_confidence"),
                "next_action": d.get("next_action"),
                "rt_ms": d.get("rt_ms"),
                "is_practice": d.get("is_practice", False),
                "is_check": d.get("is_check", False),
                "familiarity": familiarity,
                **survey_ratings,
                "attention_passed": attention_passed,
                "submitted_at": e.get("timestamp"),
            })

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return out_path
