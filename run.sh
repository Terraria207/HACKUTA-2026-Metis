#!/usr/bin/env bash
# Metis launcher for macOS and Linux: ./run.sh installs (first time) and starts the server.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3.12 || command -v python3 || true)
if [ -z "$PY" ]; then
  echo "Python 3.12 was not found. Install it (macOS: brew install python@3.12; Debian/Ubuntu: apt install python3.12 python3.12-venv) and run ./run.sh again."
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating the Python environment..."
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements.lock
echo "Starting Metis at http://127.0.0.1:8000  (Ctrl+C stops it)"
exec .venv/bin/python -m metis "$@"
