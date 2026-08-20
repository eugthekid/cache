#!/usr/bin/env bash
# Run the API server for local development.
set -euo pipefail
cd "$(dirname "$0")"
./.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
