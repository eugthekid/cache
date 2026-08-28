#!/usr/bin/env bash
# Run the API server for local development.
#
# Uses ~/.cache-venvs/cache-backend, NOT ./.venv -- backend/.venv sits under
# iCloud Drive sync (this whole project does, being under ~/Desktop), and
# --reload's worker subprocess re-imports the whole app on every restart.
# On a cold iCloud cache that import took 100+ seconds, which looked
# exactly like a hang. Moving the venv outside iCloud's sync path dropped
# that to under a second -- verified directly, not assumed. Recreate it
# with `python3.14 -m venv ~/.cache-venvs/cache-backend && ~/.cache-venvs/
# cache-backend/bin/pip install -r requirements.txt` if it's ever missing.
set -euo pipefail
cd "$(dirname "$0")"
~/.cache-venvs/cache-backend/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
