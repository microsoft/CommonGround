#!/bin/sh
set -eu

python -m pip install --editable . --no-deps
exec gunicorn --bind=0.0.0.0:${PORT:-5004} --timeout 600 uncertainty_grading.app:app