"""
config.py
---------
Same .env-loading pattern as bot/src/config.py (itself ported from
discord-checkout-tracker): secrets and machine-specific settings live in
.env, never in code.

EMAIL_ENV_PATH must stay byte-identical to backend/app/routers/
email_account.py's own EMAIL_ENV_PATH -- Settings' "Connect Email" form
writes there, and this connector has to read the exact same file, same
reasoning as bot/src/config.py's BOT_ENV_PATH docstring (which explains
the iCloud-eviction deadlock this path also avoids, by living outside the
iCloud-synced project folder entirely).
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

EMAIL_ENV_PATH = Path.home() / ".cache-venvs" / "cache-email" / "email.env"
load_dotenv(EMAIL_ENV_PATH)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required setting '{name}'. Connect an email account "
            f"first: open Cache -> Settings -> Connect Email."
        )
    return value


# --- Required settings ---
EMAIL_ADDRESS: str = _require("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD: str = _require("EMAIL_APP_PASSWORD")

# --- Optional settings ---
# Gmail-only for now -- the "Connect Email" form's own hint text
# ("Google Account -> Security -> ...") already commits to this, so no
# provider field exists yet to branch on. Overridable per-.env anyway, in
# case a Gmail-compatible alias (Google Workspace) needs a different host.
IMAP_HOST: str = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT: int = int(os.getenv("IMAP_PORT", "993"))

API_BASE_URL: str = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

# How often to poll the inbox for new mail. Gmail IMAP has no push
# notification without a separate Pub/Sub setup (out of scope for a
# local, single-user app) -- polling is the only option, so this trades
# staleness against hammering Gmail's IMAP rate limits. 120s matches
# roughly how fast a person would refresh their own inbox by hand.
POLL_SECONDS: int = int(os.getenv("EMAIL_POLL_SECONDS", "120"))

# Local, connector-owned sync state -- NOT the credential file, and
# deliberately not mirrored into Source.config server-side: sources.py
# only supports setting config at creation time (no PATCH for it), and
# this is exactly the kind of fast-changing, connector-internal detail
# (the last IMAP UID processed) that has no reason to round-trip through
# the API on every single poll. Same iCloud-safe directory as the
# credential file, for the same reason.
STATE_PATH: Path = EMAIL_ENV_PATH.parent / "state.json"
