from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("", response_model=schemas.SourceOut)
def create_source(
    type: str, name: str, config: dict | None = None, db: Session = Depends(get_db)
):
    user = crud.get_or_create_default_user(db)
    source = models.Source(user_id=user.id, type=type, name=name, config=config or {})
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("", response_model=list[schemas.SourceOut])
def list_sources(db: Session = Depends(get_db)):
    return db.query(models.Source).order_by(models.Source.created_at).all()


@router.patch("/{source_id}/synced", response_model=schemas.SourceOut)
def mark_source_synced(
    source_id: str, body: schemas.SourceSynced, db: Session = Depends(get_db)
):
    """Called by the bot after it finishes scanning a channel. This is what
    makes the NEXT scan incremental -- see routers/sync.py. Defaults to
    "now" so the common case needs no body."""
    source = db.query(models.Source).filter_by(id=source_id).first()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    from app.models import _now

    source.last_synced_at = body.last_synced_at or _now()
    db.commit()
    db.refresh(source)
    return source
