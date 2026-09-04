#!/usr/bin/env bash
# Run the Discord bot for local development. Requires the backend already
# running (../backend/run.sh) -- the bot checks this itself at startup.
#
# Uses ~/.cache-venvs/cache-bot, NOT ./.venv -- bot/.venv sits under iCloud
# Drive sync (this whole project does, being under ~/Desktop), which caused
# a reproducible `OSError: [Errno 11] Resource deadlock avoided` crash-loop
# on every launch (site.py hitting the venv's iCloud-synced pyvenv.cfg).
# Moving the venv outside iCloud's sync path fixed it -- same root cause and
# same fix as backend/run.sh. Recreate it with `python3.14 -m venv
# ~/.cache-venvs/cache-bot && ~/.cache-venvs/cache-bot/bin/pip install -r
# requirements.txt` if it's ever missing.
set -euo pipefail
cd "$(dirname "$0")"
~/.cache-venvs/cache-bot/bin/python src/bot.py
