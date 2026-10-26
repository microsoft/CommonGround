#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
exec gunicorn --bind=0.0.0.0:${PORT:-5004} --timeout 600 uncertainty_grading.app:app