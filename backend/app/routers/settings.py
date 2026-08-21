"""
settings.py
-----------
Read/write access to app_settings -- dashboard chart preferences, backup
schedule, and (via routers/license.py) local license state. Deliberately
generic: one GET/PUT pair keyed by an arbitrary string, not a dedicated
endpoint per setting, since app_settings itself is a generic key-value
store (see the model's docstring in app/models.py).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.models import _now

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[schemas.SettingOut])
def list_settings(db: Session = Depends(get_db)):
    user = crud.get_or_create_default_user(db)
    return db.query(models.AppSetting).filter_by(user_id=user.id).all()


@router.get("/{key}", response_model=schemas.SettingOut)
def get_setting(key: str, db: Session = Depends(get_db)):
    user = crud.get_or_create_default_user(db)
    setting = (
        db.query(models.AppSetting).filter_by(user_id=user.id, key=key).first()
    )
    if setting is None:
        raise HTTPException(status_code=404, detail=f"No setting for key '{key}'")
    return setting


@router.put("/{key}", response_model=schemas.SettingOut)
def upsert_setting(key: str, setting_in: schemas.SettingUpdate, db: Session = Depends(get_db)):
    """
    Upsert, not create-only: a client shouldn't need to know whether a
    setting already exists before writing it -- 'set this value' should
    just work whether it's the first time or the hundredth.
    """
    user = crud.get_or_create_default_user(db)
    setting = (
        db.query(models.AppSetting).filter_by(user_id=user.id, key=key).first()
    )
    if setting is None:
        setting = models.AppSetting(user_id=user.id, key=key, value=setting_in.value)
        db.add(setting)
    else:
        setting.value = setting_in.value
        setting.updated_at = _now()
    db.commit()
    db.refresh(setting)
    return setting
