"""
service_venv.py
----------------
Shared by routers/bot_service.py and routers/email_service.py: creates
the venv a LaunchAgent's plist points at, if one doesn't already exist,
so "Install background service" is genuinely the only step -- no
`python3.14 -m venv ... && pip install ...` typed by hand first. Also
stages each service's SOURCE outside iCloud sync (see sync_source()),
for the same underlying reason the venvs live there.

CONFIRMED LIVE (2026-09-17), not just theorized: the email connector's
LaunchAgent crash-looped for several cycles straight after a real
install, logging `OSError: [Errno 11] Resource deadlock avoided` while
importing email_ingest/src/classify.py and imap_client.py -- the exact
deadlock bot/src/config.py's BOT_ENV_PATH docstring already documented
for a venv living under iCloud sync (~/Desktop), just hit on the SOURCE
FILES instead this time, which were never moved even though the venv
was. It self-healed after several attempts (the same "warms up
eventually, but nothing guarantees it stays warm" behavior already
described for the venv case) -- self-healing is not a fix, since nothing
stops it recurring on the next reboot or the next time iCloud evicts
these files again. bot/src/bot.py sits under the identical iCloud path
and has the identical exposure; it just hadn't been caught crash-looping
yet when this was found. sync_source() below is the actual fix for
both, staging a source copy next to the venv it already doesn't share
this problem with.
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

    Safe to call on every "Install background service" click: "already
    there" is judged by a marker file written ONLY after `pip install`
    itself exits 0 -- NOT by the venv's own python binary existing.
    `python3.14 -m venv` creates that binary before a single dependency
    is installed, so checking for it alone would treat a venv whose `pip
    install` failed partway through (a network drop mid-download, the
    more likely real failure -- venv creation itself rarely fails) as
    fully done, silently handing a LaunchAgent a venv missing some of its
    dependencies. Found by tracing exactly what "already exists" was
    actually checking, not what the intent behind it was.
    """
    python_bin = venv_path / "bin" / "python"
    done_marker = venv_path / ".cache-setup-complete"
    if done_marker.exists():
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

    # Only written once pip has actually succeeded -- this, not
    # python_bin's existence, is what a retry checks (see this
    # function's own docstring on why that distinction matters).
    done_marker.write_text("ok")
    return True, ""


def sync_source(src_dir: Path, staged_dir: Path) -> None:
    """
    Copies src_dir's .py files into staged_dir, replacing whatever was
    there -- moving a service's actual source out of iCloud sync the
    same way its venv already was (see this module's docstring for the
    live crash this fixes). staged_dir should live next to that venv
    (e.g. ~/.cache-venvs/cache-email/src), so the LaunchAgent's
    ProgramArguments points there instead of into the dev checkout under
    ~/Desktop.

    Called on every install AND every restart, not just once like
    ensure_venv -- unlike a venv's dependencies, source changes on every
    edit during dev, and a stale copy would silently keep running
    whatever code existed the last time someone clicked Install. Cheap
    (plain files, no pip/venv work), so re-running it every time costs
    nothing.

    This whole mechanism is a DEV-mode stopgap. A packaged build spawns
    a PyInstaller-frozen executable instead (see backend/backend.spec
    and desktop/src/main/backend.ts) -- once bot/ and email_ingest/ get
    the same treatment, sync_source() and the live-source path it points
    at stop being used at all. Not built yet; this is what makes the
    dev/LaunchAgent path safe to rely on until then.
    """
    if staged_dir.exists():
        shutil.rmtree(staged_dir)
    shutil.copytree(src_dir, staged_dir)
