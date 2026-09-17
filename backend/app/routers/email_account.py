"""
email_account.py
-----------------
Writes/reads the email connector's env file so Settings can offer a real
"Connect Email" form instead of hand-editing a file -- same job
routers/discord.py already does for the bot token, and deliberately built
to match it: same read/write-a-.env-file shape, same iCloud-safe path
convention, same masked-suffix-only status response. See that file's own
docstring for the fuller reasoning; not repeated here.

STORAGE, decided explicitly (2026-09-16): plaintext in this .env file,
matching the Discord token's existing precedent exactly rather than
inventing a stronger bar for email alone -- Cache's threat model today is
local-machine access, not a network attacker, and having one credential
quietly more protected than the other for no principled reason is worse
than the two being consistent. This is a deliberate v1 choice, not an
oversight: revisit with a real OS-keychain design (and a separate answer
for Windows, which has no Keychain equivalent) before Cache ships to
users beyond local testing.

DOES manage the running connector: unlike the Discord bot, the email
connector is a background thread inside THIS process (see
app/email_poller.py's own docstring for why it doesn't need to be a
separate LaunchAgent-managed service the way the bot is) -- saving a
credential here starts or restarts it directly, no separate "Install
background service" step.
"""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import email_poller, schemas

router = APIRouter(prefix="/email", tags=["email"])

# Same reasoning as discord.py's BOT_ENV_PATH: outside the iCloud-synced
# project folder, because a cold read of an iCloud-evicted file from a
# background process is a reproducible deadlock, confirmed on this exact
# project already (see bot/src/config.py's BOT_ENV_PATH comment for the
# full story). Must stay the one path any future connector process loads
# from -- Settings writing to one file while a connector reads another
# would be a silent split-brain config bug, same trap discord.py's own
# comment already names.
EMAIL_ENV_PATH = Path.home() / ".cache-venvs" / "cache-email" / "email.env"
_LINE_PATTERN = re.compile(r"^([A-Z_]+)=(.*)$")

_ADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _read_env() -> dict[str, str]:
    if not EMAIL_ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in EMAIL_ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_PATTERN.match(line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def _status_from(values: dict[str, str]) -> schemas.EmailStatus:
    address = values.get("EMAIL_ADDRESS", "")
    password = values.get("EMAIL_APP_PASSWORD", "")
    configured = bool(address) and bool(password)
    return schemas.EmailStatus(
        configured=configured,
        address=address or None,
        app_password_suffix=password[-4:] if configured else None,
        polling=email_poller.is_running(),
    )


@router.get("/status", response_model=schemas.EmailStatus)
def email_status():
    return _status_from(_read_env())


@router.post("/configure", response_model=schemas.EmailStatus)
def configure_email(body: schemas.EmailConfigIn):
    existing = _read_env()

    address = body.address.strip()
    if not address or not _ADDRESS_RE.match(address):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    app_password = (
        body.app_password.strip() if body.app_password and body.app_password.strip() else existing.get("EMAIL_APP_PASSWORD", "")
    )
    if not app_password:
        raise HTTPException(status_code=400, detail="An app password is required.")

    lines = [
        "# Written by Cache's Settings -> Connect Email. Safe to hand-edit too;",
        "# Cache will only overwrite the fields shown in that form.",
        "#",
        "# STORED IN PLAINTEXT, matching bot.env's existing precedent -- see",
        "# this file's own module docstring (email_account.py) for why, and",
        "# what to revisit before shipping beyond local testing.",
        f"EMAIL_ADDRESS={address}",
        f"EMAIL_APP_PASSWORD={app_password}",
    ]

    EMAIL_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_ENV_PATH.write_text("\n".join(lines) + "\n")

    # Picks up the credential just written immediately -- restart() is a
    # stop-then-start (see email_poller.py), so this is also what makes
    # "connect for the first time" actually begin polling, not just save
    # a file for something to read later.
    email_poller.restart()

    return _status_from(_read_env())
