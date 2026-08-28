"""
run_backend.py
---------------
The entrypoint PyInstaller freezes into a standalone executable -- what
Electron's main process actually spawns in a packaged build, instead of
a developer running `./run.sh` by hand.

Two things a dev-mode `uvicorn --reload` invocation gets for free that a
packaged app can't assume at all:

1. NO TERMINAL TO RUN `alembic upgrade head` IN. A first-time user's
   database has no tables at all; migrations have to run automatically,
   every launch, before the server starts accepting requests -- silently
   idempotent on every launch after the first (alembic no-ops once the
   revision is current).

2. NO SOURCE TREE ON DISK to resolve paths against. Dev code finds
   alembic.ini and the migrations directory by walking up from
   backend/app/config.py's own __file__; a frozen build's files live
   inside PyInstaller's extraction directory (sys._MEIPASS) instead, at
   whatever relative layout the .spec file's `datas` entries put them.
   _bundled_backend_dir() below is the one place that distinction is
   made, so nothing else in the app needs to know it's running frozen.
"""

import sys
from pathlib import Path


def _bundled_backend_dir() -> Path:
    """Where alembic.ini and alembic/ actually live at runtime -- the
    PyInstaller extraction dir when frozen, this file's own directory
    otherwise (identical to how it's always been run in dev)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    backend_dir = _bundled_backend_dir()
    cfg = Config(str(backend_dir / "alembic.ini"))
    # Set explicitly rather than relying on alembic.ini's %(here)s: %(here)s
    # resolves relative to the ini file's own path, which SHOULD already be
    # correct once bundled at the same relative layout -- but the frozen
    # case is exactly the situation where "should" isn't good enough to
    # silently trust, since a wrong path here fails every future launch
    # until someone notices the app never got past migrations.
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    from app.config import settings

    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


def main() -> None:
    print("Cache backend starting...", flush=True)
    run_migrations()
    print("Migrations up to date.", flush=True)

    import uvicorn

    from app.config import settings
    from app.main import app

    # No --reload, no multiprocessing worker/reloader split: that machinery
    # is what a live dev server needs to pick up file edits, and it's also
    # exactly what was implicated in this session's startup hangs. A
    # packaged build never edits its own files, so there's nothing to
    # reload -- one process, serving directly, is both simpler and faster
    # to start.
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")


if __name__ == "__main__":
    main()
