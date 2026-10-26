"""Run grading directly from a source checkout without installing the package."""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uncertainty_grading.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
