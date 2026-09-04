"""
bot_service.py
---------------
Installs the Discord bot as a macOS LaunchAgent, so it survives without
anyone opening a terminal.

WHY THIS EXISTS: the bot deliberately stays a separate process from Cache
(see discord.py's docstring -- closing Cache shouldn't stop checkouts being
logged), but until now "separate process" meant the user had to remember to
run `cd bot && ./run.sh` by hand, every time, forever, including after every
reboot. A LaunchAgent is macOS's built-in answer to "keep this running,
start it at login, restart it if it dies" -- the same mechanism apps like
Dropbox's helper process use. Installing one turns the bot from a chore
into something the user never thinks about again.

Deliberately macOS-only for now (LaunchAgents are a Darwin-specific
mechanism -- Linux would need systemd user units, Windows a scheduled
task). Cache only ships for macOS today, so there's nothing to build yet
for the other platforms; when that changes, this file gets a sibling per
platform, not a rewrite.
"""

import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import schemas
from app.config import PROJECT_ROOT
from app.routers.discord import BOT_ENV_PATH, _read_env, _status_from

router = APIRouter(prefix="/discord/service", tags=["discord"])

LABEL = "com.cache.discordbot"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{LABEL}.plist"
LOG_DIR = Path.home() / "Library" / "Logs" / "Cache"
LOG_PATH = LOG_DIR / "bot.log"

BOT_DIR = Path(PROJECT_ROOT) / "bot"
# NOT BOT_DIR / ".venv" -- on a dev checkout under iCloud Drive sync (e.g.
# anything under ~/Desktop), launchd invoking a venv's python there hits a
# reproducible `OSError: [Errno 11] Resource deadlock avoided` crash-loop
# (site.py stalking the venv's iCloud-synced pyvenv.cfg). Same root cause
# and same fix as backend/run.sh: a relocated venv outside iCloud's sync
# path. Recreate it with `python3.14 -m venv ~/.cache-venvs/cache-bot &&
# ~/.cache-venvs/cache-bot/bin/pip install -r bot/requirements.txt` if
# it's ever missing.
VENV_PYTHON = Path.home() / ".cache-venvs" / "cache-bot" / "bin" / "python"
BOT_SCRIPT = BOT_DIR / "src" / "bot.py"


def _require_macos() -> None:
    if platform.system() != "Darwin":
        raise HTTPException(
            status_code=400,
            detail="Running the bot as a background service is only supported on macOS right now.",
        )


def _gui_domain() -> str:
    # launchd's per-user domain; every launchctl call below targets this
    # rather than the older, now-deprecated load/unload commands.
    import os

    return f"gui/{os.getuid()}"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def _plist_xml() -> str:
    import plistlib

    data = {
        "Label": LABEL,
        # -u: unbuffered stdout/stderr. Without it, Python block-buffers when
        # writing to a file (rather than a terminal), so print()s can sit in
        # memory for a long time before StandardOutPath actually shows them
        # -- exactly when someone's looking at the log because something
        # seems wrong.
        "ProgramArguments": [str(VENV_PYTHON), "-u", str(BOT_SCRIPT)],
        "WorkingDirectory": str(BOT_DIR),
        "RunAtLoad": True,
        # KeepAlive=True (not the SuccessfulExit form): the bot is meant to
        # run forever and never exits on its own, so ANY exit -- crash or
        # otherwise -- should be treated as something to recover from.
        "KeepAlive": True,
        # Caps how fast launchd will restart a bot stuck in a crash loop
        # (e.g. a bad token) rather than hammering Discord's API.
        "ThrottleInterval": 10,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }
    return plistlib.dumps(data).decode("utf-8")


def _is_loaded() -> bool:
    result = _run(["launchctl", "print", f"{_gui_domain()}/{LABEL}"])
    return result.returncode == 0


def _is_running() -> bool:
    result = _run(["launchctl", "print", f"{_gui_domain()}/{LABEL}"])
    if result.returncode != 0:
        return False
    return "pid = " in result.stdout


def _service_status() -> schemas.BotServiceStatus:
    installed = PLIST_PATH.exists() and _is_loaded()
    return schemas.BotServiceStatus(
        supported=platform.system() == "Darwin",
        installed=installed,
        running=installed and _is_running(),
        log_path=str(LOG_PATH),
    )


@router.get("/status", response_model=schemas.BotServiceStatus)
def service_status():
    if platform.system() != "Darwin":
        return schemas.BotServiceStatus(supported=False, installed=False, running=False, log_path=None)
    return _service_status()


@router.post("/install", response_model=schemas.BotServiceStatus)
def install_service():
    """
    Writes the LaunchAgent plist and registers it with launchd. Safe to
    call again after the user edits the Discord form (Settings does this
    automatically) -- bootstrapping over an already-loaded label is a
    no-op error we swallow, then `restart` picks up the new bot/.env.
    """
    _require_macos()

    status = _status_from(_read_env())
    if not status.configured:
        raise HTTPException(
            status_code=400,
            detail="Connect Discord (token + server ID) before installing the background service.",
        )

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_plist_xml())

    if not _is_loaded():
        result = _run(["launchctl", "bootstrap", _gui_domain(), str(PLIST_PATH)])
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"launchctl bootstrap failed: {result.stderr.strip() or result.stdout.strip()}",
            )
    _run(["launchctl", "enable", f"{_gui_domain()}/{LABEL}"])
    _run(["launchctl", "kickstart", "-k", f"{_gui_domain()}/{LABEL}"])

    return _service_status()


@router.post("/uninstall", response_model=schemas.BotServiceStatus)
def uninstall_service():
    _require_macos()
    if _is_loaded():
        result = _run(["launchctl", "bootout", f"{_gui_domain()}/{LABEL}"])
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"launchctl bootout failed: {result.stderr.strip() or result.stdout.strip()}",
            )
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return _service_status()


@router.post("/restart", response_model=schemas.BotServiceStatus)
def restart_service():
    """
    Needed because bot/src/config.py loads .env once at process startup
    (python-dotenv) -- editing the token or channel scope through Settings
    writes the new file to disk immediately, but a LaunchAgent-managed bot
    process won't see it until it's restarted. Settings calls this right
    after a successful /discord/configure whenever the service is running.
    """
    _require_macos()
    if not _is_loaded():
        raise HTTPException(status_code=400, detail="The background service isn't installed.")
    result = _run(["launchctl", "kickstart", "-k", f"{_gui_domain()}/{LABEL}"])
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"launchctl kickstart failed: {result.stderr.strip() or result.stdout.strip()}",
        )
    return _service_status()
