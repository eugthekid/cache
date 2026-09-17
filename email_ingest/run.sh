#!/usr/bin/env bash
# Run the email connector for local development. Requires the backend
# already running (../backend/run.sh) -- checked at startup, same as
# bot/run.sh.
#
# Uses ~/.cache-venvs/cache-email, NOT ./.venv -- same reasoning as
# bot/run.sh: this project directory sits under iCloud Drive sync, which
# causes a reproducible `OSError: [Errno 11] Resource deadlock avoided`
# crash-loop for anything reading a venv (or a credential file) from
# inside it. This is also the SAME directory backend/app/routers/
# email_account.py already writes email.env into, so the venv and the
# credential it reads at startup live side by side, same layout as
# cache-bot's venv + bot.env.
#
# Create it with:
#   python3.14 -m venv ~/.cache-venvs/cache-email
#   ~/.cache-venvs/cache-email/bin/pip install -r requirements.txt
set -euo pipefail
cd "$(dirname "$0")"
~/.cache-venvs/cache-email/bin/python src/main.py
