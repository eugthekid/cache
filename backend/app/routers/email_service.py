"""
email_service.py
------------------
Installs the email connector (email_ingest/src/main.py) as a macOS
LaunchAgent -- the exact same job routers/bot_service.py does for the
Discord bot, deliberately built to match it: same plist shape, same
launchctl commands, same auto-created-venv step via app/service_venv.py.
See that file's own docstring for the fuller reasoning; not repeated
here beyond what differs.

WHAT DIFFERS FROM bot_service.py: the connector polls IMAP on a timer
rather than holding a persistent gateway connection, but that distinction
doesn't matter to launchd -- both are just "a process that should run
forever, restarting if it dies," which is exactly what KeepAlive=True
gives either one.
"""

import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import schemas
from app.config import PROJECT_ROOT
from app.routers.email_account import _read_env, _status_from
from app.service_venv import ensure_venv

router = APIRouter(prefix="/email/service", tags=["email"])

LABEL = "com.cache.emailconnector"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{LABEL}.plist"
LOG_DIR = Path.home() / "Library" / "Logs" / "Cache"
LOG_PATH = LOG_DIR / "email.log"

EMAIL_DIR = Path(PROJECT_ROOT) / "email_ingest"
# Same directory EMAIL_ENV_PATH already writes email.env into (see
# email_account.py) -- venv and credential side by side, same layout as
# cache-bot's venv + bot.env.
VENV_PATH = Path.home() / ".cache-venvs" / "cache-email"
VENV_PYTHON = VENV_PATH / "bin" / "python"
MAIN_SCRIPT = EMAIL_DIR / "src" / "main.py"


def _require_macos() -> None:
    if platform.system() != "Darwin":
        raise HTTPException(
            status_code=400,
            detail="Running the email connector as a background service is only supported on macOS right now.",
        )


def _gui_domain() -> str:
    import os

    return f"gui/{os.getuid()}"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def _plist_xml() -> str:
    import plistlib

    data = {
        "Label": LABEL,
        "ProgramArguments": [str(VENV_PYTHON), "-u", str(MAIN_SCRIPT)],
        "WorkingDirectory": str(EMAIL_DIR),
        "RunAtLoad": True,
        "KeepAlive": True,
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


def _service_status() -> schemas.EmailServiceStatus:
    installed = PLIST_PATH.exists() and _is_loaded()
    return schemas.EmailServiceStatus(
        supported=platform.system() == "Darwin",
        installed=installed,
        running=installed and _is_running(),
        log_path=str(LOG_PATH),
    )


@router.get("/status", response_model=schemas.EmailServiceStatus)
def service_status():
    if platform.system() != "Darwin":
        return schemas.EmailServiceStatus(supported=False, installed=False, running=False, log_path=None)
    return _service_status()


@router.post("/install", response_model=schemas.EmailServiceStatus)
def install_service():
    """
    Writes the LaunchAgent plist and registers it with launchd. Creates
    ~/.cache-venvs/cache-email first if it doesn't exist yet -- see
    app/service_venv.py -- so this is genuinely the only step, no
    `python3.14 -m venv ...` typed by hand first.
    """
    _require_macos()

    status = _status_from(_read_env())
    if not status.configured:
        raise HTTPException(
            status_code=400,
            detail="Connect Email (address + app password) before installing the background service.",
        )

    ok, message = ensure_venv(VENV_PATH, EMAIL_DIR / "requirements.txt")
    if not ok:
        raise HTTPException(status_code=500, detail=message)

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


@router.post("/uninstall", response_model=schemas.EmailServiceStatus)
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


@router.post("/restart", response_model=schemas.EmailServiceStatus)
def restart_service():
    """
    Needed because email_ingest/src/config.py loads email.env once at
    process startup (python-dotenv) -- editing the address or app
    password through Settings writes the new file to disk immediately,
    but a LaunchAgent-managed connector won't see it until restarted.
    Settings calls this right after a successful /email/configure
    whenever the service is running.
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
