"""
service_venv.py
----------------
Shared by routers/bot_service.py and routers/email_service.py: creates
the venv a LaunchAgent's plist points at, if one doesn't already exist,
so "Install background service" is genuinely the only step -- no
`python3.14 -m venv ... && pip install ...` typed by hand first.

Both services' venvs already lived outside the iCloud-synced project
folder for the same deadlock-avoidance reason (see bot/src/config.py's
BOT_ENV_PATH docstring for the full story) -- this module doesn't change
where they live, only who creates them.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Tried in order. python3.14 is what every venv on THIS machine was
# created with by hand so far (see bot/run.sh's own comments), but a
# fresh install of Cache on someone else's Mac might only have a
# different 3.x on PATH -- the first one found wins, rather than failing
# outright just because it isn't exactly 3.14.
_PYTHON_CANDIDATES = ["python3.14", "python3.13", "python3.12", "python3.11", "python3"]


def _find_python() -> Optional[str]:
    for name in _PYTHON_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def ensure_venv(venv_path: Path, requirements_path: Path) -> tuple[bool, str]:
    """
    Creates venv_path (a real venv, with pip) and installs
    requirements_path into it, unless one already exists there. Returns
    (ok, message) -- message is a human-readable error on failure, empty
    on success (including "was already there, did nothing").

    Safe to call on every "Install background service" click: an
    existing venv is detected by its own python binary actually being
    present, not just the directory existing -- a half-created venv left
    over from an interrupted previous attempt (network dropped mid-`pip
    install`, say) is retried rather than treated as done and handed to
    a LaunchAgent that would just crash-loop against it.
    """
    python_bin = venv_path / "bin" / "python"
    if python_bin.exists():
        return True, ""

    system_python = _find_python()
    if system_python is None:
        return False, (
            "No Python 3 interpreter found on this machine. Install Python 3 "
            "(from python.org, or `brew install python3`) and try again."
        )

    venv_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        create = subprocess.run(
            [system_python, "-m", "venv", str(venv_path)],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out creating the environment (60s). Try again."
    if create.returncode != 0:
        return False, f"Couldn't create the environment: {(create.stderr or create.stdout).strip()}"

    try:
        install = subprocess.run(
            [str(python_bin), "-m", "pip", "install", "-q", "-r", str(requirements_path)],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out installing dependencies (180s) -- check your network connection and try again."
    if install.returncode != 0:
        # Trimmed: pip's own failure output can run long (a full
        # dependency resolution trace), and this string round-trips
        # into an HTTPException detail the Settings UI shows inline --
        # the LAST couple thousand characters are where the actual
        # error usually sits, not the top of a long log.
        detail = (install.stderr or install.stdout).strip()
        return False, f"Couldn't install dependencies: {detail[-2000:]}"

    return True, ""
