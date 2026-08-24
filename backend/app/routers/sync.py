"""
sync.py
-------
Lets the desktop app ask the Discord bot to re-scan, without Cache having
to own the bot's process.

The bot runs separately and deliberately stays that way (closing Cache
must not stop checkouts being logged), so there's no way to "call" it.
Instead this is a tiny request queue: the app POSTs /sync/request, the bot
polls /sync/claim on a timer and picks the request up. One pending request
at a time -- clicking Resync five times shouldn't queue five full history
walks.

Two kinds of scan, and the difference matters at volume:
  incremental -- only messages newer than a channel's last_synced_at. What
                 the bot does on every normal startup.
  full        -- the entire channel history again, ignoring last_synced_at.
                 What the Resync button asks for, and the only thing that
                 recovers data if the local database was wiped.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.models import _now

router = APIRouter(prefix="/sync", tags=["sync"])

_SETTING_KEY = "sync_request"


def _get_setting(db: Session, user_id: str) -> Optional[models.AppSetting]:
    return db.query(models.AppSetting).filter_by(user_id=user_id, key=_SETTING_KEY).first()


def _write_setting(db: Session, user_id: str, value: dict) -> None:
    setting = _get_setting(db, user_id)
    if setting is None:
        setting = models.AppSetting(user_id=user_id, key=_SETTING_KEY, value=value)
        db.add(setting)
    else:
        setting.value = value
        setting.updated_at = _now()
    db.commit()


def _sources_payload(db: Session) -> list[schemas.SyncSourceStatus]:
    sources = (
        db.query(models.Source)
        .filter(models.Source.type == "discord_channel")
        .order_by(models.Source.name)
        .all()
    )
    return [
        schemas.SyncSourceStatus(
            id=s.id, name=s.name, last_synced_at=s.last_synced_at
        )
        for s in sources
    ]


@router.get("/status", response_model=schemas.SyncStatus)
def sync_status(db: Session = Depends(get_db)):
    user = crud.get_or_create_default_user(db)
    setting = _get_setting(db, user.id)
    value = setting.value if setting else {}
    return schemas.SyncStatus(
        pending=bool(value.get("pending")),
        requested_at=value.get("requested_at"),
        full=bool(value.get("full")),
        sources=_sources_payload(db),
    )


@router.post("/request", response_model=schemas.SyncStatus)
def request_sync(body: schemas.SyncRequest, db: Session = Depends(get_db)):
    """Queue a scan for the bot to pick up. Idempotent by design: a second
    request while one is still pending just refreshes it rather than
    stacking up another full history walk."""
    user = crud.get_or_create_default_user(db)
    _write_setting(
        db,
        user.id,
        {"pending": True, "full": bool(body.full), "requested_at": _now().isoformat()},
    )
    return sync_status(db)


@router.post("/claim", response_model=schemas.SyncClaim)
def claim_sync(db: Session = Depends(get_db)):
    """Called by the BOT, not the UI. Returns whether a scan was requested
    and clears the flag in the same step, so one request produces exactly
    one scan even if the bot polls frequently."""
    user = crud.get_or_create_default_user(db)
    setting = _get_setting(db, user.id)
    value = setting.value if setting else {}
    claimed = bool(value.get("pending"))
    full = bool(value.get("full"))
    if claimed:
        _write_setting(db, user.id, {"pending": False, "full": False, "claimed_at": _now().isoformat()})
    return schemas.SyncClaim(claimed=claimed, full=full)
