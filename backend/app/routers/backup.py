"""
backup.py
---------
Export/restore as one `.cache` file (a zip: the raw SQLite db + a
manifest.json carrying the schema version). See docs/DATA-MODEL.md and the
Settings screen design for why this is a full-fidelity file bundle rather
than the readable .xlsx export (routers/import.py handles that side).

Preview and restore are deliberately two separate calls, not one: the
restore confirmation screen needs to show counts and the schema-version
comparison BEFORE anything touches the live database, and re-uploading for
the actual restore is a small cost for never doing a destructive action
sight-unseen.

Schema version comes straight from the `alembic_version` table via a plain
sqlite3 connection, not through Alembic's own (slow-importing) machinery --
this only ever needs to read one row, so there's no reason to pay for
Alembic's full startup cost on every export/restore/preview call.
"""

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.database import engine

router = APIRouter(prefix="/backup", tags=["backup"])

_MANIFEST_NAME = "manifest.json"
_DB_NAME_IN_BUNDLE = "app.db"


def _live_db_path() -> Path:
    if not settings.database_url.startswith("sqlite:///"):
        raise HTTPException(
            status_code=400,
            detail="Backup/restore only supports the local SQLite database.",
        )
    return Path(settings.database_url.removeprefix("sqlite:///"))


def _schema_version(db_path: Path) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("select version_num from alembic_version").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None  # no alembic_version table -- not a valid app database
    finally:
        conn.close()


def _counts(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        orders = conn.execute("select count(*) from orders").fetchone()[0]
        items = conn.execute("select count(*) from inventory_items").fetchone()[0]
        return {"orders": orders, "inventory_items": items}
    except sqlite3.OperationalError:
        return {"orders": 0, "inventory_items": 0}
    finally:
        conn.close()


@router.post("/export")
def export_backup():
    """Bundles the live db + a manifest into a .cache file and returns it
    as a download. The manifest's schema_version is what a future restore
    compares against -- see the module docstring."""
    db_path = _live_db_path()
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="No database found to back up.")

    manifest = {
        "schema_version": _schema_version(db_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app": "cache",
    }

    out_path = Path(tempfile.gettempdir()) / f"cache-backup-{datetime.now(timezone.utc):%Y-%m-%d}.cache"
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, arcname=_DB_NAME_IN_BUNDLE)
        zf.writestr(_MANIFEST_NAME, json.dumps(manifest, indent=2))

    return FileResponse(
        out_path,
        media_type="application/zip",
        filename=out_path.name,
    )


def _extract_and_validate(upload_bytes: bytes) -> tuple[Path, dict]:
    """Shared by preview and restore: unpack the upload into a fresh temp
    dir, and fail loudly (400, not a silent best-effort) on anything that
    isn't a real .cache bundle."""
    work_dir = Path(tempfile.mkdtemp(prefix="cache-restore-"))
    zip_path = work_dir / "upload.zip"
    zip_path.write_bytes(upload_bytes)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if _MANIFEST_NAME not in names or _DB_NAME_IN_BUNDLE not in names:
                raise HTTPException(
                    status_code=400,
                    detail="Not a valid backup file -- missing the database or manifest.",
                )
            zf.extractall(work_dir)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="That file isn't a valid backup (.cache).")

    manifest = json.loads((work_dir / _MANIFEST_NAME).read_text())
    return work_dir / _DB_NAME_IN_BUNDLE, manifest


@router.post("/preview")
async def preview_restore(file: UploadFile):
    """Read-only: never touches the live database. Backs the restore
    confirmation screen's file summary and schema-version comparison."""
    bundled_db, manifest = _extract_and_validate(await file.read())

    return {
        "filename": file.filename,
        "created_at": manifest.get("created_at"),
        "backup_schema_version": manifest.get("schema_version"),
        "current_schema_version": _schema_version(_live_db_path()),
        **_counts(bundled_db),
    }


@router.post("/restore")
async def restore_backup(file: UploadFile):
    """
    The actual swap. Refuses a schema-version mismatch outright (409)
    rather than restoring into a database shape this app version doesn't
    know how to read -- silently "restoring" corrupted state is worse than
    a clear error asking the user to update the app first. Before
    overwriting anything, the current live db is copied aside (never
    deleted), so a bad restore can always be undone by hand.
    """
    bundled_db, manifest = _extract_and_validate(await file.read())
    live_db = _live_db_path()

    backup_version = manifest.get("schema_version")
    current_version = _schema_version(live_db)
    if backup_version != current_version:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This backup is from schema version {backup_version}, but this app "
                f"expects {current_version}. Restoring it as-is isn't safe."
            ),
        )

    safety_copy = live_db.with_name(
        f"{live_db.stem}.pre-restore-{datetime.now(timezone.utc):%Y%m%d%H%M%S}{live_db.suffix}"
    )
    if live_db.exists():
        shutil.copy2(live_db, safety_copy)

    # Release every pooled connection before swapping the file out from
    # under them -- SQLite is fine with the file changing underneath a
    # *closed* connection, not an open one.
    engine.dispose()
    shutil.copy2(bundled_db, live_db)

    counts = _counts(live_db)
    return {
        "restored": True,
        "restart_required": True,
        "safety_copy": str(safety_copy) if live_db.exists() else None,
        **counts,
    }
