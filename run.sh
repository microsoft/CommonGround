#!/usr/bin/env bash
# CommonGround puzzle launcher (macOS/Linux).
#
# Usage:
#   ./run.sh human-ai                 # human worker + AI helper
#   ./run.sh human-ai --role helper   # AI worker + human helper
#   ./run.sh human-human              # two humans (prints shared links)
#   ./run.sh ai-ai --limit 1          # headless AI vs AI
set -euo pipefail
PY="python"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi
exec "$PY" run.py "$@"
