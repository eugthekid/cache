"""
discord.py
----------
Writes/reads bot/.env so Settings can offer a real "Connect Discord" form
instead of hand-editing a file. Deliberately NOT process management -- the
bot stays a separate, independently-run process (see run.sh) so that
closing Cache doesn't stop checkouts from being logged. This only helps
with the part that was actually tedious: finding and typing in the right
IDs.

Works because the backend runs from this same source checkout, so
bot/.env is just a normal sibling file on disk -- this does not (yet)
solve writing config for a packaged, bot-less distribution.
"""

import platform
import re

from fastapi import APIRouter, HTTPException

from app import schemas
from app.config import PROJECT_ROOT

router = APIRouter(prefix="/discord", tags=["discord"])

BOT_ENV_PATH = PROJECT_ROOT / "bot" / ".env"
_LINE_PATTERN = re.compile(r"^([A-Z_]+)=(.*)$")


def _read_env() -> dict[str, str]:
    if not BOT_ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in BOT_ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_PATTERN.match(line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def _status_from(values: dict[str, str]) -> schemas.DiscordStatus:
    token = values.get("DISCORD_TOKEN", "")
    configured = bool(token) and "paste-your-bot-token-here" not in token
    raw_channels = values.get("CHANNEL_IDS", "").strip()
    is_all = raw_channels.lower() == "all"
    return schemas.DiscordStatus(
        configured=configured,
        token_suffix=token[-4:] if configured else None,
        guild_id=values.get("GUILD_ID") or None,
        channel_scope="all" if is_all else ("specific" if raw_channels else None),
        channel_ids=None if is_all else (raw_channels or None),
        profile_filter=values.get("PROFILE_FILTER") or None,
    )


@router.get("/status", response_model=schemas.DiscordStatus)
def discord_status():
    return _status_from(_read_env())


@router.post("/configure", response_model=schemas.DiscordStatus)
def configure_discord(body: schemas.DiscordConfigIn):
    existing = _read_env()

    token = body.token.strip() if body.token and body.token.strip() else existing.get("DISCORD_TOKEN", "")
    if not token or "paste-your-bot-token-here" in token:
        raise HTTPException(status_code=400, detail="A bot token is required.")

    guild_id = body.guild_id.strip()
    if not guild_id or not guild_id.isdigit():
        raise HTTPException(status_code=400, detail="Server (guild) ID must be numeric.")

    if body.channel_scope == "all":
        channel_ids_value = "all"
    elif body.channel_scope == "specific":
        channel_ids_value = (body.channel_ids or "").strip()
        if not channel_ids_value:
            raise HTTPException(status_code=400, detail="List at least one channel ID, or choose 'All channels'.")
    else:
        raise HTTPException(status_code=400, detail="channel_scope must be 'all' or 'specific'.")

    lines = [
        "# Written by Cache's Settings -> Connect Discord. Safe to hand-edit too;",
        "# Cache will only overwrite the fields shown in that form.",
        f"DISCORD_TOKEN={token}",
        f"CHANNEL_IDS={channel_ids_value}",
        f"GUILD_ID={guild_id}",
        "API_BASE_URL=http://127.0.0.1:8000",
    ]
    profile_filter = (body.profile_filter or "").strip()
    if profile_filter:
        lines.append(f"PROFILE_FILTER={profile_filter}")

    BOT_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOT_ENV_PATH.write_text("\n".join(lines) + "\n")

    # bot/src/config.py reads .env once at process startup, so a
    # LaunchAgent-managed bot won't see this new token/scope until it's
    # restarted. Only matters if the service is actually installed --
    # importing here (not at module load) avoids a circular import between
    # discord.py and bot_service.py.
    from app.routers import bot_service

    if platform.system() == "Darwin" and bot_service._is_loaded():
        bot_service._run(["launchctl", "kickstart", "-k", f"{bot_service._gui_domain()}/{bot_service.LABEL}"])

    return _status_from(_read_env())
