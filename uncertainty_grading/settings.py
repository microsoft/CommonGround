"""Central configuration for the Study 4 rating web app.

All paths are resolved relative to this module so the app can be launched from
any working directory. Environment variables (loaded from a local ``.env``)
override the defaults. ``UNCERTAINTY_GRADING_*`` names are preferred; legacy
``STUDY4_*`` names remain accepted for existing deployments.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
MODULE_DIR = Path(__file__).resolve().parent

STIMULI_DIR = MODULE_DIR / "stimuli"
SNAPSHOTS_DIR = STIMULI_DIR / "snapshots"
# Rendered Helper-view board PNGs (target board + per-snapshot worker board).
BOARDS_DIR = STIMULI_DIR / "boards"
SNAPSHOT_MATRIX_CSV = STIMULI_DIR / "snapshot_matrix.csv"

DATA_DIR = MODULE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"                          # per-participant JSONL (gitignored)
GRADINGS_DIR = DATA_DIR / "gradings"                # per-participant grading JSONL
EXPORTS_DIR = DATA_DIR / "exports"
PRACTICE_MANIFEST_JSON = STIMULI_DIR / "practice_manifest.json"

ENV_PREFIX = "UNCERTAINTY_GRADING_"
LEGACY_ENV_PREFIX = "STUDY4_"
DEVELOPMENT_SECRET = "dev-insecure-change-me"


def _env(name: str, default: str) -> str:
    """Read a standalone setting, falling back to its legacy Study 4 name."""
    return os.environ.get(
        f"{ENV_PREFIX}{name}",
        os.environ.get(f"{LEGACY_ENV_PREFIX}{name}", default),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{ENV_PREFIX}{name} must be true or false, got {raw!r}")


def _env_int(name: str, default: int) -> int:
    raw = _env(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"{ENV_PREFIX}{name} must be an integer, got {raw!r}") from error


def _ensure_dirs() -> None:
    for d in (
        STIMULI_DIR,
        SNAPSHOTS_DIR,
        BOARDS_DIR,
        DATA_DIR,
        RAW_DIR,
        GRADINGS_DIR,
        EXPORTS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
class Settings:
    """Runtime configuration, populated from the environment with defaults."""

    def __init__(self) -> None:
        load_dotenv(MODULE_DIR / ".env")

        # Paths (exposed on the instance so callers can use `settings.X`)
        self.MODULE_DIR = MODULE_DIR
        self.STIMULI_DIR = STIMULI_DIR
        self.SNAPSHOTS_DIR = SNAPSHOTS_DIR
        self.BOARDS_DIR = BOARDS_DIR
        self.SNAPSHOT_MATRIX_CSV = SNAPSHOT_MATRIX_CSV
        self.DATA_DIR = DATA_DIR
        self.RAW_DIR = RAW_DIR
        self.GRADINGS_DIR = GRADINGS_DIR
        self.EXPORTS_DIR = EXPORTS_DIR
        self.PRACTICE_MANIFEST_JSON = PRACTICE_MANIFEST_JSON

        # Flask
        self.SECRET_KEY = _env("SECRET_KEY", DEVELOPMENT_SECRET)
        self.HOST = _env("HOST", "127.0.0.1")
        self.PORT = _env_int("PORT", 5004)
        self.DEBUG = _env_bool("DEBUG", False)
        self.COOKIE_SECURE = _env_bool("COOKIE_SECURE", True)
        self.COOKIE_SAMESITE = _env("COOKIE_SAMESITE", "Lax")
        self.SESSION_LIFETIME_MINUTES = _env_int("SESSION_LIFETIME_MINUTES", 180)
        self.TRUST_PROXY_PROTO = _env_bool("TRUST_PROXY_PROTO", True)
        self.HSTS_ENABLED = _env_bool("HSTS_ENABLED", True)
        self.HSTS_MAX_AGE = _env_int("HSTS_MAX_AGE", 31536000)
        self.HSTS_INCLUDE_SUBDOMAINS = _env_bool("HSTS_INCLUDE_SUBDOMAINS", True)
        self.HSTS_PRELOAD = _env_bool("HSTS_PRELOAD", False)

        # Study identity
        self.STUDY_ID = _env("ID", "uncertainty_grading")
        self.PROLIFIC_COMPLETION_URL = _env(
            "PROLIFIC_COMPLETION_URL",
            "https://app.prolific.com/submissions/complete?cc=REPLACE_ME",
        )
        # Prolific completion CODE shown as text on the final page (no button).
        self.PROLIFIC_COMPLETION_CODE = _env("PROLIFIC_COMPLETION_CODE", "")

        # --- Experimental design (v5.0 trajectory) ------------------------- #
        # Between-subjects factorial: condition (A=Baseline / B=Candidate Pieces /
        # C=Unambiguous Description / D=Diagnostic Uncertainty /
        # E=Confidence-Triggered Uncertainty) x rating type
        # (CB=before the Worker turn / CA=after). Each
        # participant is assigned one cell and rotated onto one of the sessions;
        # within that session they rate every rateable Worker turn (trajectory).
        #
        # ``ARMS`` keeps its name for backwards-compatible iteration but now
        # denotes the **rating type**; ``CONDITIONS`` denotes the AI style.
        self.CONDITIONS = ("A", "C", "D", "E", "B")
        self.ARMS = ("CB", "CA")
        self.CONDITION_VERSIONS = {
            "A": "A", "B": "B", "C": "C5", "D": "D2", "E": "E1",
        }
        # Conditions that ALSO show the "candidate pieces" panel (all 24 staging
        # pieces the Worker chooses from) to the left of the Target board.
        # Condition B == Baseline Worker text (as A) + candidate-pieces panel.
        self.CANDIDATE_CONDITIONS = {"B"}
        # Size of the staging pool shown in the candidate-pieces panel (matches
        # puzzle_constants.NUM_PIECES). The panel is shuffled per view so a
        # piece's grid position never reveals its id.
        self.NUM_STAGING_PIECES = 24
        # Between-subjects cells (condition, rating_type). A=Baseline,
        # C=Unambiguous Description, D=Diagnostic Uncertainty,
        # E=Confidence-Triggered Uncertainty, B=Baseline + candidate pieces.
        self.CELLS = (("A", "CB"), ("A", "CA"), ("C", "CB"), ("C", "CA"),
                      ("D", "CB"), ("D", "CA"), ("E", "CB"), ("E", "CA"),
                      ("B", "CB"), ("B", "CA"))
        # Each participant grades the whole conversation of **trial 2 and trial
        # 3** of one session: every rateable Worker turn, in order, is a rating
        # point (W1, W2, ... Wn). The number of points varies by session, so it
        # is read from the built snapshot matrix rather than fixed here.
        # Number of practice rating steps shown before the graded trials.
        self.NUM_PRACTICE_STEPS = _env_int("NUM_PRACTICE_STEPS", 2)

        # Slider
        self.SLIDER_MIN = 0
        self.SLIDER_MAX = 100

        # Target visibility is normally a per-session property derived from the
        # session's view (shared -> shown, non-shared -> hidden). This global
        # flag is an optional override: when true the Target Puzzle grid is
        # hidden for **every** stimulus regardless of view, for testing.
        self.HIDE_TARGET = _env_bool("HIDE_TARGET", False)

        _ensure_dirs()

    def runtime_problems(self) -> list[str]:
        """Return missing or unusable inputs required to serve the study."""
        problems = []
        required_files = (
            self.SNAPSHOT_MATRIX_CSV,
            self.PRACTICE_MANIFEST_JSON,
        )
        for path in required_files:
            if not path.is_file():
                problems.append(f"Missing runtime file: {path}")
        if not self.SNAPSHOTS_DIR.is_dir() or not any(self.SNAPSHOTS_DIR.glob("*.json")):
            problems.append(f"No generated snapshots found in {self.SNAPSHOTS_DIR}")
        if not self.BOARDS_DIR.is_dir() or not any(self.BOARDS_DIR.glob("*.png")):
            problems.append(f"No generated board images found in {self.BOARDS_DIR}")
        return problems

    def production_problems(self) -> list[str]:
        """Return insecure settings that must be corrected for production."""
        problems = []
        if self.SECRET_KEY == DEVELOPMENT_SECRET:
            problems.append(f"{ENV_PREFIX}SECRET_KEY still uses the development value")
        if self.DEBUG:
            problems.append(f"{ENV_PREFIX}DEBUG must be false")
        if not self.COOKIE_SECURE:
            problems.append(f"{ENV_PREFIX}COOKIE_SECURE must be true")
        if not self.HSTS_ENABLED:
            problems.append(f"{ENV_PREFIX}HSTS_ENABLED must be true")
        return problems


settings = Settings()
