from fastapi import APIRouter, Depends
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
