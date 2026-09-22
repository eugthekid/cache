"""
tracking_account.py
--------------------
Writes/reads the live-tracking provider's env file so Settings can offer
a real "Connect tracking" form instead of hand-editing one -- same job
routers/email_account.py does for the email connector, and deliberately
built to match it: same read/write-a-.env-file shape, same iCloud-safe
path convention, same masked-suffix-only status response. See that
file's own docstring for the fuller reasoning; not repeated here.

STORAGE: plaintext in this .env file, matching email.env's and bot.env's
existing precedent for the same reason email_account.py gives -- one
credential quietly more protected than the others for no principled
reason is worse than all three being consistent. Same v1-choice caveat:
revisit with real OS-keychain storage before shipping beyond local
testing (see [[cache-credential-storage-security]]).

DOES manage the running poller: like the email connector (unlike the
Discord bot), tracking_poller.py is a background thread inside THIS
process -- saving a key here starts or restarts it directly, no separate
install step.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import schemas, tracking_poller

router = APIRouter(prefix="/tracking", tags=["tracking"])

# Same iCloud-eviction-deadlock reasoning as EMAIL_ENV_PATH/BOT_ENV_PATH --
# outside the project folder, on the one path any future poller process
# loads from.
TRACKING_ENV_PATH = Path.home() / ".cache-venvs" / "cache-tracking" / "tracking.env"


def _read_env() -> dict[str, str]:
    if not TRACKING_ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in TRACKING_ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key] = value
    return values


def _status_from(values: dict[str, str]) -> schemas.TrackingStatus:
    api_key = values.get("TRACKING_API_KEY", "")
    configured = bool(api_key)
    return schemas.TrackingStatus(
        configured=configured,
        provider="17track" if configured else None,
        api_key_suffix=api_key[-4:] if configured else None,
        polling=tracking_poller.is_running(),
    )


@router.get("/status", response_model=schemas.TrackingStatus)
def tracking_status():
    return _status_from(_read_env())


@router.post("/configure", response_model=schemas.TrackingStatus)
def configure_tracking(body: schemas.TrackingConfigIn):
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="An API key is required.")

    lines = [
        "# Written by Cache's Settings -> Connect tracking. Safe to hand-edit too;",
        "# Cache will only overwrite the field shown in that form.",
        "#",
        "# STORED IN PLAINTEXT, matching email.env's existing precedent -- see",
        "# this file's own module docstring (tracking_account.py) for why, and",
        "# what to revisit before shipping beyond local testing.",
        f"TRACKING_API_KEY={api_key}",
    ]

    TRACKING_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACKING_ENV_PATH.write_text("\n".join(lines) + "\n")

    tracking_poller.restart()

    return _status_from(_read_env())


@router.post("/disconnect", response_model=schemas.TrackingStatus)
def disconnect_tracking():
    """Clears the saved key and stops the poller -- the "turn this off"
    path Settings needs alongside "connect"."""
    if TRACKING_ENV_PATH.exists():
        TRACKING_ENV_PATH.unlink()
    tracking_poller.stop()
    return _status_from(_read_env())
