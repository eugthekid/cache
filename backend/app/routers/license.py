"""
license.py
----------
Activation against the shared TEST_LICENSE_KEY in config.py -- see that
constant's docstring for why this is intentionally not real per-customer
licensing yet. State is stored as an app_settings row (key='license'),
not a dedicated table: see AppSetting's docstring in app/models.py for why.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.config import TEST_LICENSE_KEY
from app.database import get_db
from app.models import _now

router = APIRouter(prefix="/license", tags=["license"])

_SETTING_KEY = "license"


def _get_license_setting(db: Session, user_id: str) -> models.AppSetting | None:
    return (
        db.query(models.AppSetting)
        .filter_by(user_id=user_id, key=_SETTING_KEY)
        .first()
    )


@router.get("/status", response_model=schemas.LicenseStatus)
def license_status(db: Session = Depends(get_db)):
    user = crud.get_or_create_default_user(db)
    setting = _get_license_setting(db, user.id)
    if setting is None or not setting.value.get("activated"):
        return schemas.LicenseStatus(activated=False)

    return schemas.LicenseStatus(
        activated=True,
        key_suffix=setting.value.get("key", "")[-4:] or None,
        activated_at=setting.value.get("activated_at"),
    )


@router.post("/activate", response_model=schemas.LicenseStatus)
def activate(body: schemas.LicenseActivate, db: Session = Depends(get_db)):
    """
    Case-insensitive, whitespace-tolerant compare -- a pasted key with
    trailing whitespace or the wrong case shouldn't fail for reasons that
    have nothing to do with whether it's the right key.
    """
    submitted = body.key.strip().upper()
    if submitted != TEST_LICENSE_KEY:
        raise HTTPException(status_code=400, detail="That key isn't valid.")

    user = crud.get_or_create_default_user(db)
    now = _now()
    value = {"activated": True, "key": submitted, "activated_at": now.isoformat()}

    setting = _get_license_setting(db, user.id)
    if setting is None:
        setting = models.AppSetting(user_id=user.id, key=_SETTING_KEY, value=value)
        db.add(setting)
    else:
        setting.value = value
        setting.updated_at = now
    db.commit()

    return schemas.LicenseStatus(
        activated=True, key_suffix=submitted[-4:], activated_at=now
    )
