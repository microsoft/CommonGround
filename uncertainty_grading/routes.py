"""Routes / participant flow for Study 4.

The flow is modelled as an ordered list of *steps* stored in the session
(``session['steps']``) with a pointer (``session['step_ptr']``). Each step is a
``"kind:index"`` token. ``GET /flow`` renders the current step; ``POST /flow``
records the response, logs it, and advances the pointer. This keeps the
two arms (CB / CA) on a single linear engine with arm-specific step lists.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from flask import (Blueprint, abort, current_app, redirect, render_template,
                   request, send_file, send_from_directory, session, url_for)

from . import assignment, storage
from .settings import settings as S

bp = Blueprint("study4", __name__)

# Gold-standard "check turn" snapshot types interleaved into every flow.
PRACTICE_CHECK_TYPES = ["CHKP"]
TRIAL_CHECK_TYPES = ["CHK1", "CHK2"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _practice_cells(condition: str, arm: str, dialogue_id: str):
    """Practice rating points from the participant's assigned dialogue.

    Practice uses puzzle 1 snapshots generated per dialogue (``P1W*``), then the
    main graded flow continues with trial-2/trial-3 snapshots.
    """
    cells = []
    if S.PRACTICE_MANIFEST_JSON.exists():
        manifest = json.loads(S.PRACTICE_MANIFEST_JSON.read_text(encoding="utf-8"))
        entries = manifest.get("sessions", [])
        entry = next((e for e in entries if e.get("dialogue_id") == dialogue_id), None)
        if entry is None:
            return cells
        for snapshot_type in entry.get("snapshot_types", [])[:S.NUM_PRACTICE_STEPS]:
            cells.append({
                "dialogue_id": dialogue_id,
                "condition": condition,
                "snapshot_type": snapshot_type,
                "arm": arm,
            })
    return cells


def _build_steps(arm: str, n_main: int, n_practice: int):
    steps = ["instructions"]
    steps += [f"practice:{i}" for i in range(n_practice)]
    steps += [f"trial:{i}" for i in range(n_main)]
    steps += ["familiarity", "questionnaire", "done"]
    return steps


def _current_step():
    steps = session.get("steps", [])
    ptr = session.get("step_ptr", 0)
    if ptr >= len(steps):
        return "done"
    return steps[ptr]


def _advance():
    session["step_ptr"] = session.get("step_ptr", 0) + 1


def _require_session():
    return session.get("credentials") and session.get("consent_given", False)


def _refresh_flow_state_if_needed():
    """Heal stale in-cookie flow state after snapshot/manifest rebuilds.

    If a participant started before a rebuild, ``session['practice']`` and
    ``session['steps']`` can reference old snapshot ids. Recompute from current
    roster/manifest and keep the pointer clamped.
    """
    cred = session.get("credentials")
    if not cred:
        return

    row = assignment.row_for_credentials(cred)
    if row is None:
        return

    condition = row["condition"]
    arm = row["arm"]
    dialogues = row["dialogues"]
    first = dialogues[0] if dialogues else row.get("dialogue_id", "")
    expected_trials = row["trials"]
    expected_practice = _practice_cells(condition, arm, first)

    # Checks (is_check cells) are interleaved into practice/trials at random
    # positions by _init_flow; compare only the underlying (check-stripped)
    # assignment so a request does not silently strip them.
    if (_strip_checks(session.get("trials")) == expected_trials and
            _strip_checks(session.get("practice")) == expected_practice):
        return

    session["condition"] = condition
    session["condition_version"] = S.CONDITION_VERSIONS.get(condition, condition)
    session["arm"] = arm
    session["dialogue_id"] = first
    session["dialogues"] = dialogues
    session["view"] = row.get("view", "")
    session["source_view"] = row.get("source_view", "")
    session["trials"] = _build_trials(dialogues, condition, arm)
    session["practice"] = _insert_checks(
        list(expected_practice), condition, arm, first, PRACTICE_CHECK_TYPES)

    steps = _build_steps(arm, len(session["trials"]), len(session["practice"]))
    old_ptr = int(session.get("step_ptr", 0))
    session["steps"] = steps
    session["step_ptr"] = min(max(old_ptr, 0), max(len(steps) - 1, 0))
    _warn_if_checks_missing("refresh")


def _resolve_snapshot(cell, arm):
    return storage.load_snapshot(
        cell["dialogue_id"], cell["condition"], cell["snapshot_type"], arm)


def _insert_checks(cells, condition, arm, dialogue_id, check_types):
    """Interleave catch 'check turn' cells at random positions (only if built)."""
    out = list(cells)
    for stype in check_types:
        if storage.load_snapshot(dialogue_id, condition, stype, arm) is None:
            continue
        out.insert(random.randint(0, len(out)),
                   {"dialogue_id": dialogue_id, "condition": condition,
                    "snapshot_type": stype, "arm": arm, "is_check": True})
    return out


def _strip_checks(cells):
    """The underlying (non-check) assignment cells, for stale-state comparison."""
    return [c for c in (cells or []) if not c.get("is_check")]


def _session_dialogues():
    """The participant's ordered dialogue list (falls back to the single id)."""
    dl = session.get("dialogues")
    if dl:
        return list(dl)
    d = session.get("dialogue_id")
    return [d] if d else []


def _insert_dialogue_check(cells, condition, arm, dialogue_id):
    """Embed exactly one gold check (a random built CHK*) in one dialogue's block."""
    built = [t for t in TRIAL_CHECK_TYPES
             if storage.load_snapshot(dialogue_id, condition, t, arm) is not None]
    if not built:
        return list(cells)
    return _insert_checks(cells, condition, arm, dialogue_id, [random.choice(built)])


def _build_trials(dialogues, condition, arm):
    """Concatenate each dialogue's rating points (in order), one check embedded each."""
    out = []
    for d in dialogues:
        out.extend(_insert_dialogue_check(
            assignment._trials_for(condition, arm, d), condition, arm, d))
    return out


def _warn_if_checks_missing(where: str) -> None:
    """Log a warning if the assembled flow lost any interleaved gold checks.

    Expects one gold check per graded dialogue plus one practice check. Guards
    against both a missing CHK* snapshot and any regression that strips the
    interleaved checks (as _refresh_flow_state_if_needed once did).
    """
    dialogues = _session_dialogues()
    exp_trial = len(dialogues)
    exp_prac = len(PRACTICE_CHECK_TYPES)
    trial_chk = sum(1 for c in session.get("trials", []) if c.get("is_check"))
    prac_chk = sum(1 for c in session.get("practice", []) if c.get("is_check"))
    if trial_chk >= exp_trial and prac_chk >= exp_prac:
        return
    current_app.logger.warning(
        "study4: checks missing (%s) cred=%s dialogues=%s cond=%s arm=%s -> "
        "trial=%d/%d practice=%d/%d", where, session.get("credentials"),
        ";".join(dialogues), session.get("condition"), session.get("arm"),
        trial_chk, exp_trial, prac_chk, exp_prac)
    cred = session.get("credentials")
    if cred:
        storage.log_event(cred, "checks_missing", {
            "where": where, "dialogues": dialogues,
            "trial_checks": trial_chk, "trial_expected": exp_trial,
            "practice_checks": prac_chk, "practice_expected": exp_prac,
        }, arm=session.get("arm"))


# --------------------------------------------------------------------------- #
# Entry / consent
# --------------------------------------------------------------------------- #
@bp.route("/")
def index():
    if session.get("is_admin"):
        return redirect(url_for("study4.admin"))
    if not session.get("consent_given", False):
        return redirect(url_for("study4.consent"))
    if not session.get("credentials"):
        return redirect(url_for("study4.login"))
    return redirect(url_for("study4.flow"))


@bp.route("/consent", methods=["GET", "POST"])
def consent():
    if request.method == "POST":
        if request.form.get("agree") == "yes":
            session["consent_given"] = True
            return redirect(url_for("study4.login"))
        return redirect(url_for("study4.consent_declined"))
    return render_template("consent.html")


@bp.route("/consent-declined")
def consent_declined():
    return render_template("consent_declined.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not session.get("consent_given", False):
        return redirect(url_for("study4.consent"))
    if request.method == "POST":
        prolific_id = (request.form.get("prolific_id") or "").strip()
        credentials = (request.form.get("credentials") or "").strip()
        if not credentials:
            return render_template("login.html",
                                   error="Please enter your credentials to continue.")
        row = assignment.row_for_credentials(credentials)
        if row is None:
            return render_template(
                "login.html",
                error="Invalid credentials. Please check and try again, or contact the researcher.")

        # Admin credential: skip the study; go to the data-download console.
        if row.get("is_admin"):
            session.clear()
            session["consent_given"] = True
            session["is_admin"] = True
            session["credentials"] = credentials
            return redirect(url_for("study4.admin"))

        if not prolific_id:
            return render_template("login.html",
                                   error="Please enter your Prolific ID to continue.")

        session.clear()
        session["consent_given"] = True
        session["prolific_id"] = prolific_id
        session["credentials"] = credentials
        session["participant_index"] = row["row_index"]
        session["condition"] = row["condition"]
        session["condition_version"] = S.CONDITION_VERSIONS.get(
            row["condition"], row["condition"])
        session["arm"] = row["arm"]
        session["dialogue_id"] = row["dialogue_id"]
        session["dialogues"] = row["dialogues"]
        session["view"] = row.get("view", "")
        session["source_view"] = row.get("source_view", "")
        session["trials"] = row["trials"]

        cred = session["credentials"]
        storage.log_event(cred, "session_started",
                          {"participant_index": session["participant_index"],
                           "prolific_id": session["prolific_id"]},
                          arm=session["arm"])
        storage.log_event(cred, "arm_assigned",
                          {"arm": session["arm"], "condition": session["condition"],
                           "session": session["dialogue_id"]},
                          arm=session["arm"])
        _init_flow()
        return redirect(url_for("study4.flow"))
    return render_template("login.html", error=None)


@bp.route("/start", methods=["POST"])
def start():
    # Legacy endpoint retained for compatibility with older templates.
    return redirect(url_for("study4.login"))


def _init_flow():
    """Build this participant's trajectory plan and steps."""
    arm = session["arm"]
    condition = session["condition"]
    dialogues = _session_dialogues()
    first = dialogues[0] if dialogues else session.get("dialogue_id", "")
    # Practice comes from the FIRST dialogue only (one practice block); the main
    # flow concatenates every graded dialogue, each with one gold check embedded.
    session["practice"] = _insert_checks(
        _practice_cells(condition, arm, first),
        condition, arm, first, PRACTICE_CHECK_TYPES)
    session["trials"] = _build_trials(dialogues, condition, arm)
    session["steps"] = _build_steps(arm, len(session["trials"]),
                                    len(session["practice"]))
    session["step_ptr"] = 0
    session["trial_started_at"] = time.time()
    session["consented"] = True
    _warn_if_checks_missing("init_flow")


# --------------------------------------------------------------------------- #
# Main flow engine
# --------------------------------------------------------------------------- #
@bp.route("/flow", methods=["GET"])
def flow():
    if session.get("is_admin"):
        return redirect(url_for("study4.admin"))
    if not _require_session():
        return redirect(url_for("study4.index"))
    _refresh_flow_state_if_needed()
    step = _current_step()
    kind = step.split(":")[0]
    arm = session["arm"]
    session["trial_started_at"] = time.time()

    if kind == "instructions":
        return render_template("instructions.html", arm=arm,
                               n_main=len(session["trials"]),
                               n_practice=len(session["practice"]),
                               n_convs=len(_session_dialogues()) or 1,
                               show_candidates=session["condition"] in S.CANDIDATE_CONDITIONS,
                               hide_worker=session.get("view") != "shared")

    if kind in ("practice", "trial"):
        idx = int(step.split(":")[1])
        is_practice = kind == "practice"
        cell = (session["practice"] if is_practice else session["trials"])[idx]
        snap = _resolve_snapshot(cell, arm)
        if snap is None:
            _advance()
            return redirect(url_for("study4.flow"))
        total = len(session["practice"]) if is_practice else len(session["trials"])
        # The Helper always sees the Target. The Worker's progress board is shown
        # or hidden by the PRESENTED view (session["view"], from the roster),
        # decoupled from the dialogue's original group -- so a non-shared-sourced
        # dialogue can be shown WITH the board and vice versa. The global
        # HIDE_TARGET flag can force-hide the Target for testing.
        hide_target = S.HIDE_TARGET
        hide_worker = session.get("view") != "shared"
        show_candidates = bool(snap.get("show_candidates"))
        candidate_pieces = None
        if show_candidates:
            # Shuffle the pool per view so a piece's grid position does not
            # reveal its id (ids also appear in the transcript's move lines).
            order = list(range(S.NUM_STAGING_PIECES))
            random.shuffle(order)
            candidate_pieces = [f"piece_{i:02d}.png" for i in order]
        # Multi-dialogue: which conversation this is, and whether it just started
        # (main trials only; practice comes from the first dialogue).
        dialogues = _session_dialogues()
        n_convs = len(dialogues)
        conv_index = 0
        is_conv_start = False
        if not is_practice and n_convs > 1 and cell["dialogue_id"] in dialogues:
            conv_index = dialogues.index(cell["dialogue_id"]) + 1
            prev = session["trials"][idx - 1] if idx > 0 else None
            is_conv_start = prev is None or prev["dialogue_id"] != cell["dialogue_id"]
        return render_template("trial.html", arm=arm, snapshot=snap,
                               condition=session["condition"],
                               is_practice=is_practice, index=idx, total=total,
                               hide_target=hide_target, hide_worker=hide_worker,
                               show_candidates=show_candidates,
                               candidate_pieces=candidate_pieces,
                               is_check=bool(snap.get("is_check")),
                               n_convs=n_convs, conv_index=conv_index,
                               is_conv_start=is_conv_start,
                               slider_min=S.SLIDER_MIN, slider_max=S.SLIDER_MAX)

    if kind == "familiarity":
        return render_template("familiarity.html")

    if kind == "questionnaire":
        return render_template("questionnaire.html")

    return redirect(url_for("study4.done"))


@bp.route("/flow", methods=["POST"])
def flow_submit():
    if not _require_session():
        return redirect(url_for("study4.index"))
    _refresh_flow_state_if_needed()
    step = _current_step()
    kind = step.split(":")[0]
    arm = session["arm"]
    cred = session["credentials"]
    rt_ms = int((time.time() - session.get("trial_started_at", time.time())) * 1000)

    if kind == "instructions":
        storage.log_event(cred, "pledge_accepted",
                          {"accepted": request.form.get("pledge") == "on"}, arm=arm)

    if kind in ("practice", "trial"):
        idx = int(step.split(":")[1])
        is_practice = kind == "practice"
        cell = (session["practice"] if is_practice else session["trials"])[idx]
        snap = _resolve_snapshot(cell, arm)
        rating = request.form.get("rating", type=int)
        worker_confidence = request.form.get("worker_confidence", type=int)
        next_action = request.form.get("next_action")
        storage.log_event(cred, "rating_submitted", {
            "snapshot_id": snap["snapshot_id"] if snap else None,
            "dialogue_id": cell["dialogue_id"],
            "condition": cell["condition"],
            "condition_version": snap.get("condition_version") if snap else None,
            "snapshot_type": cell["snapshot_type"],
            "puzzle_number": snap.get("puzzle_number") if snap else None,
            "shared_view": session.get("view") == "shared",
            "view": session.get("view"),
            "source_view": session.get("source_view"),
            "word_count": snap["word_count"] if snap else None,
            "ground_truth_piece": snap.get("ground_truth_piece") if snap else None,
            "placed_piece": snap.get("placed_piece") if snap else None,
            "worker_correct": snap.get("worker_correct") if snap else None,
            "rating": rating,
            "worker_confidence": worker_confidence,
            "next_action": next_action,
            "rt_ms": rt_ms,
            "trial_index": idx,
            "is_practice": is_practice,
            "is_check": bool(snap.get("is_check")) if snap else False,
        }, arm=arm)
        # Also log to gradings JSONL file
        if snap and rating is not None:
            storage.log_grading(
                credentials=cred,
                participant_id=session.get("prolific_id", ""),
                dialogue_id=cell["dialogue_id"],
                condition=cell["condition"],
                condition_version=snap.get("condition_version"),
                view=session.get("view", ""),
                turn=cell["snapshot_type"],
                grade=rating,
                rt_ms=rt_ms,
                arm=arm,
                next_action=next_action,
                worker_confidence=worker_confidence,
                source_view=session.get("source_view", ""),
                is_check=bool(snap.get("is_check")),
            )

    elif kind == "familiarity":
        f = request.form
        storage.log_event(cred, "familiarity_submitted", {
            "value": f.get("familiarity", type=int),
            "ai_trust": f.get("ai_trust", type=int),
            "ai_understand": f.get("ai_understand", type=int),
            "ai_detect_uncertainty": f.get("ai_detect_uncertainty", type=int),
            "pair_same_page": f.get("pair_same_page", type=int),
            "pair_ai_understood": f.get("pair_ai_understood", type=int),
            "pair_smooth": f.get("pair_smooth", type=int),
            "pair_repeated": f.get("pair_repeated", type=int),
        }, arm=arm)

    elif kind == "questionnaire":
        # Attention check: the carried-over "Antarctica / palm trees" item.
        passed = request.form.get("attention") == "no"
        storage.log_event(cred, "attention_check", {"passed": passed}, arm=arm)
        storage.log_event(cred, "questionnaire_submitted",
                          {"free_text": (request.form.get("free_text") or "")[:2000]},
                          arm=arm)

    _advance()
    if _current_step() == "done":
        return redirect(url_for("study4.done"))
    return redirect(url_for("study4.flow"))


@bp.route("/done")
def done():
    cred = session.get("credentials")
    condition = session.get("condition")
    condition_version = session.get("condition_version") or S.CONDITION_VERSIONS.get(
        condition, condition)
    if cred:
        storage.log_event(cred, "completed", {"prolific_id": session.get("prolific_id", "")},
                          arm=session.get("arm"))
        if not session.get("debrief_shown"):
            storage.log_event(cred, "debrief_shown", {
                "condition": condition,
                "condition_version": condition_version,
            }, arm=session.get("arm"))
            session["debrief_shown"] = True
    return render_template("done.html",
                           completion_code=S.PROLIFIC_COMPLETION_CODE,
                           condition=condition,
                           condition_version=condition_version)


# --------------------------------------------------------------------------- #
# Admin data console (raw grading / event-log downloads)
# --------------------------------------------------------------------------- #
def _require_admin() -> bool:
    return bool(session.get("is_admin"))


@bp.route("/admin")
def admin():
    if not _require_admin():
        return redirect(url_for("study4.login"))
    gradings = sorted(p.name for p in S.GRADINGS_DIR.glob("grading_*.jsonl"))
    raw = sorted(p.name for p in S.RAW_DIR.glob("participant_*.jsonl"))
    return render_template("admin.html", gradings=gradings, raw=raw)


@bp.route("/admin/download/<kind>/<path:filename>")
def admin_download(kind: str, filename: str):
    if not _require_admin():
        return redirect(url_for("study4.login"))
    directory = {"gradings": S.GRADINGS_DIR, "raw": S.RAW_DIR}.get(kind)
    if directory is None:
        abort(404)
    # send_from_directory safely rejects path traversal outside `directory`.
    return send_from_directory(directory, filename, as_attachment=True)


@bp.route("/admin/download-all")
def admin_download_all():
    if not _require_admin():
        return redirect(url_for("study4.login"))
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for directory, sub in ((S.GRADINGS_DIR, "gradings"), (S.RAW_DIR, "raw")):
            for p in sorted(directory.glob("*.jsonl")):
                z.write(p, f"{sub}/{p.name}")
    buf.seek(0)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"study4_data_{stamp}.zip")


# --------------------------------------------------------------------------- #
# Static stimulus assets + admin export
# --------------------------------------------------------------------------- #
@bp.route("/board/<path:filename>")
def board_image(filename):
    return send_from_directory(S.BOARDS_DIR, filename)


@bp.route("/admin/export")
def admin_export():
    out = storage.export_long_csv()
    return {"status": "ok", "file": str(out)}
