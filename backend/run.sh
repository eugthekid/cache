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

# app/ itself (unlike .venv) can't be relocated -- --reload needs to watch
# it in place. iCloud can still evict its .py files to dataless
# placeholders between edits (doesn't require the disk to be full, just
# time since last access), and a bare re-import during --reload's reload
# cycle doesn't go through the NSFileCoordinator dance that would trigger
# a transparent download -- it hits a 60s read timeout and crashes that
# worker instead, with no auto-recovery from the reloader. Confirmed via
# a real traceback: TimeoutError: [Errno 60] Operation timed out out of
# importlib's get_data(). brctl download -R forces every file local
# BEFORE uvicorn starts, so at least the reload cycles that follow start
# from a warm tree; it only queues the download rather than blocking on
# it, so this is a best-effort head start, not a guarantee.
brctl download -R app >/dev/null 2>&1 || true

~/.cache-venvs/cache-backend/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
