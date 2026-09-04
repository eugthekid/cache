"""
config.py
---------
Same .env-loading pattern as discord-checkout-tracker's config.py (and this
project's backend/app/config.py): secrets and machine-specific settings
live in .env, never in code.

Ported wholesale from discord-checkout-tracker: the token, guild/channel
scoping, and SUCCESS_KEYWORD logic are unchanged, because the Discord-side
behavior (which channels to watch, how to recognize a checkout card) hasn't
changed -- only where a parsed checkout ends up afterward has (see
api_client.py). discord-checkout-tracker itself is left untouched; this is
a new, separate bot, not a modification of that project.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# NOT PROJECT_ROOT/.env -- that sits under iCloud Drive sync (this whole
# project does, being under ~/Desktop). If iCloud has evicted it to a
# dataless placeholder (it doesn't need the disk to be full -- it also ages
# out rarely-touched files), a launchd-spawned process reading it hits a
# reproducible `OSError: [Errno 11] Resource deadlock avoided`: bare
# open()/read() doesn't go through the NSFileCoordinator dance the
# FileProvider framework needs to materialize the file first, and the
# kernel's synchronous wait for that deadlocks rather than transparently
# downloading it. A foreground/interactive read doesn't reliably hit this
# (confirmed directly: the exact same file, once warmed by one read, was
# then read fine by a LaunchAgent-spawned process with no code change) --
# but nothing guarantees the file stays warm, so the fix is to keep it
# somewhere iCloud never touches. Same root cause and same fix as the
# .venv relocation in bot/run.sh and bot_service.py's VENV_PYTHON. Recreate
# it by copying bot/.env's contents to this path if it's ever missing.
BOT_ENV_PATH = Path.home() / ".cache-venvs" / "cache-bot" / "bot.env"
load_dotenv(BOT_ENV_PATH)


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required setting '{name}'. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


# --- Required settings ---
DISCORD_TOKEN: str = _require("DISCORD_TOKEN")
GUILD_ID: int = int(_require("GUILD_ID"))

_raw_channels = (os.getenv("CHANNEL_IDS") or "").strip()
SCAN_ALL_CHANNELS: bool = _raw_channels.lower() == "all"
CHANNEL_IDS: set[int] = (
    set()
    if SCAN_ALL_CHANNELS
    else {int(x) for x in _raw_channels.replace(",", " ").split() if x}
)

if not SCAN_ALL_CHANNELS and not CHANNEL_IDS:
    raise RuntimeError(
        "No channels configured. In your .env set CHANNEL_IDS=all to watch the "
        "whole server, or CHANNEL_IDS=<id>,<id> to watch specific channels."
    )


def should_scan(channel_id: int) -> bool:
    if channel_id == CHANGELOG_CHANNEL_ID:
        return False
    return SCAN_ALL_CHANNELS or channel_id in CHANNEL_IDS


# --- Optional settings ---
SUCCESS_KEYWORD: str = os.getenv("SUCCESS_KEYWORD", "success")

_raw_changelog_channel = os.getenv("CHANGELOG_CHANNEL_ID", "").strip()
CHANGELOG_CHANNEL_ID: Optional[int] = (
    int(_raw_changelog_channel) if _raw_changelog_channel else None
)

# --- New for inventory-tracker: where the FastAPI backend lives. Every
# parsed checkout is POSTed here instead of written to a local SQLite file
# the way discord-checkout-tracker's database.py did.
API_BASE_URL: str = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

# --- New for inventory-tracker: an ingestion-time profile filter. Every
# checkout already carries a `profile` field (parsed in parser.py from the
# embed's "Profile"/"Profile Name" field) -- this is the first thing that
# actually reads it before a message is stored, rather than just recording
# it. Unset/empty means "keep everything" (the old, only) behavior, so this
# is opt-in and never breaks an existing setup.
_raw_profile_filter = (os.getenv("PROFILE_FILTER") or "").strip()
PROFILE_FILTER: list[str] = [p.strip().lower() for p in _raw_profile_filter.split(",") if p.strip()]


def matches_profile_filter(profile: Optional[str]) -> bool:
    """Case-insensitive substring match, same convention discord-checkout-
    tracker's own /export profile filter used -- 'eugene' matches
    'eugene1', 'eugene_alt', etc, not just an exact profile name. A
    checkout with no profile field at all is dropped once a filter is
    configured, since there's no way to tell whose it is."""
    if not PROFILE_FILTER:
        return True
    if not profile:
        return False
    profile_lower = profile.lower()
    return any(term in profile_lower for term in PROFILE_FILTER)
