#!/usr/bin/env bash
# Run the Discord bot for local development. Requires the backend already
# running (../backend/run.sh) -- the bot checks this itself at startup.
set -euo pipefail
cd "$(dirname "$0")"
./.venv/bin/python src/bot.py
