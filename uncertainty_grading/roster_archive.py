r"""Roster archival + historical credential resolution for Study 4.

The live ``data/participant_roster.csv`` is deliberately mutable: it is rewritten
on every ``make_credentials`` run and may be hand-edited between runs. To keep
participant tracking stable across those changes, this module

  * archives a timestamped copy of the roster into ``data/roster_snapshots/``
    on every write (``snapshot_roster``), and
  * resolves any credential -- e.g. one observed in ``results/`` -- against the
    union of the live roster and every archived snapshot (``resolve`` /
    ``load_history``), so a participant is never orphaned after the live roster
    is trimmed, reordered, or regenerated.

No separate ledger is kept: the snapshots ARE the history. Everything lives under
``data/`` (gitignored), so credentials are never committed.

CLI (run from the standalone folder)::

    ../.venv/Scripts/python.exe -m uncertainty_grading.roster_archive snapshot
    ../.venv/Scripts/python.exe -m uncertainty_grading.roster_archive list
    ../.venv/Scripts/python.exe -m uncertainty_grading.roster_archive resolve <cred>
    ../.venv/Scripts/python.exe -m uncertainty_grading.roster_archive audit
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .settings import settings as S

ROSTER_CSV = S.DATA_DIR / "participant_roster.csv"
SNAPSHOTS_DIR = S.DATA_DIR / "roster_snapshots"
# Ad-hoc backups made before this module existed; still counted as history.
_LEGACY_BAK_GLOB = "participant_roster.bak_*.csv"
_TS_RE = re.compile(r"(\d{8}_\d{6})")
_ASSIGN_FIELDS = ("participant_id", "row_index", "dialogue_id", "dialogues",
                  "view", "condition", "arm")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snapshot_time(path: Path) -> datetime:
    """Timestamp of a snapshot, parsed from its name (falling back to mtime)."""
    m = _TS_RE.search(path.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").replace(
                tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def list_snapshots() -> List[Path]:
    """All archived rosters (new snapshots + legacy .bak_ files), oldest first."""
    snaps = list(SNAPSHOTS_DIR.glob("participant_roster_*.csv")) \
        if SNAPSHOTS_DIR.exists() else []
    legacy = list(S.DATA_DIR.glob(_LEGACY_BAK_GLOB))
    return sorted(snaps + legacy, key=_snapshot_time)


def snapshot_roster(reason: str = "") -> Optional[Path]:
    """Archive the current roster into roster_snapshots/.

    Returns the snapshot path, or ``None`` if the roster does not exist or is
    byte-identical to the most recent snapshot (so repeated no-op writes do not
    pile up duplicates).
    """
    if not ROSTER_CSV.exists():
        return None
    current = ROSTER_CSV.read_text(encoding="utf-8")
    snaps = list_snapshots()
    if snaps and _digest(snaps[-1].read_text(encoding="utf-8")) == _digest(current):
        return None
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = SNAPSHOTS_DIR / f"participant_roster_{_now_stamp()}.csv"
    i = 1
    while dest.exists():  # two snapshots within the same second
        dest = SNAPSHOTS_DIR / f"participant_roster_{_now_stamp()}_{i}.csv"
        i += 1
    dest.write_text(current, encoding="utf-8")
    return dest


def _read_rows(path: Path) -> List[Dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_history() -> Dict[str, Dict]:
    """Map every credential ever seen -> latest assignment + provenance.

    Unions all snapshots (oldest first) then the live roster, so the returned
    assignment is the most recent one. Each entry also carries ``first_seen`` /
    ``last_seen`` snapshot timestamps and a ``conflict`` flag set if the
    credential's assignment (dialogue/condition/arm/view) ever changed.
    """
    sources: List[tuple] = [(_snapshot_time(p), p.name, _read_rows(p))
                            for p in list_snapshots()]
    if ROSTER_CSV.exists():
        sources.append((datetime.now(timezone.utc), ROSTER_CSV.name,
                        _read_rows(ROSTER_CSV)))
    sources.sort(key=lambda s: s[0])

    hist: Dict[str, Dict] = {}
    for ts, label, rows in sources:
        for r in rows:
            cred = (r.get("credentials") or "").strip()
            if not cred:
                continue
            assign = {k: r.get(k) for k in _ASSIGN_FIELDS}
            stamp = ts.isoformat()
            e = hist.get(cred)
            if e is None:
                hist[cred] = {"credentials": cred, **assign,
                              "first_seen": stamp, "last_seen": stamp,
                              "first_source": label, "last_source": label,
                              "conflict": False}
                continue
            drift = (e.get("dialogues"), e["dialogue_id"], e["condition"],
                     e["arm"], e["view"]) != (
                assign.get("dialogues"), assign["dialogue_id"],
                assign["condition"], assign["arm"], assign["view"])
            e.update(assign)
            e["last_seen"] = stamp
            e["last_source"] = label
            e["conflict"] = e["conflict"] or drift
    return hist


def resolve(credential: str) -> Optional[Dict]:
    """A single credential's assignment + provenance across all history."""
    cred = (credential or "").strip()
    if not cred:
        return None
    return load_history().get(cred)


def _result_credentials() -> List[str]:
    if not S.RAW_DIR.exists():
        return []
    return [p.stem[len("participant_"):] for p in
            S.RAW_DIR.glob("participant_*.jsonl")]


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Study 4 roster archive / history.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot", help="Archive the current roster now.")
    sub.add_parser("list", help="List archived roster snapshots.")
    rp = sub.add_parser("resolve", help="Resolve a credential to its assignment.")
    rp.add_argument("credential")
    sub.add_parser("audit", help="Result credentials not found in any roster/snapshot.")
    args = ap.parse_args()

    if args.cmd == "snapshot":
        p = snapshot_roster("manual")
        print(f"Archived -> {p}" if p else
              "No change since the last snapshot; nothing archived.")
    elif args.cmd == "list":
        for p in list_snapshots():
            rows = len(p.read_text(encoding="utf-8").splitlines()) - 1
            print(f"{_snapshot_time(p).isoformat()}  {p.name}  ({rows} rows)")
        print(f"live roster: {'present' if ROSTER_CSV.exists() else 'MISSING'}")
    elif args.cmd == "resolve":
        e = resolve(args.credential)
        print(json.dumps(e, indent=2) if e else
              "Credential not found in the roster history.")
    elif args.cmd == "audit":
        hist = load_history()
        seen = _result_credentials()
        real = [c for c in seen if re.fullmatch(r"[0-9a-f]{32}", c)]
        orphan = sorted(c for c in real if c not in hist)
        print(f"result files: {len(seen)}  (real-looking creds: {len(real)})")
        print(f"NOT in any roster/snapshot: {len(orphan)}")
        for c in orphan:
            print(f"  ORPHAN {c}")


if __name__ == "__main__":
    _main()
