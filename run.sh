#!/usr/bin/env bash
# One-command local start: creates a virtualenv, installs deps, migrates, runs.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r backend/requirements-dev.txt
cd backend
python -m app.migrations
echo "JobPilot AI → http://127.0.0.1:8000"
exec uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --reload-dir ../frontend
