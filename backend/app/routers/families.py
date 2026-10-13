"""
families.py (router)
--------------------
Group products that are versions of one item, see one row for the family, and
move units out of a "random" version once you know what they were. All the
logic lives in app/families.py.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, families, schemas
from app.database import get_db

router = APIRouter(prefix="/families", tags=["families"])


def _user(db: Session):
    return crud.get_or_create_default_user(db)


def _fail(db: Session, exc: ValueError) -> HTTPException:
    db.rollback()
    return HTTPException(status_code=422, detail=str(exc))


@router.post("", response_model=schemas.FamilyDashboard)
def create(body: schemas.FamilyCreate, db: Session = Depends(get_db)):
    user = _user(db)
    try:
        family = families.create_family(db, user.id, body.name, [m.model_dump() for m in body.members])
    except ValueError as exc:
        raise _fail(db, exc)
    db.commit()
    return families.family_dashboard(db, user.id, family)


@router.get("/{family_id}/dashboard", response_model=schemas.FamilyDashboard)
def dashboard(family_id: str, db: Session = Depends(get_db)):
    user = _user(db)
    try:
        family = families.get_family(db, user.id, family_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Family not found")
    return families.family_dashboard(db, user.id, family)


@router.patch("/{family_id}", response_model=schemas.FamilyDashboard)
def update(family_id: str, body: schemas.FamilyUpdate, db: Session = Depends(get_db)):
    user = _user(db)
    try:
        family = families.get_family(db, user.id, family_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Family not found")
    families.update_family(db, family, body.model_dump(exclude_unset=True))
    db.commit()
    return families.family_dashboard(db, user.id, family)


@router.delete("/{family_id}")
def ungroup(family_id: str, db: Session = Depends(get_db)):
    """Forget the grouping. Every product and unit is left exactly as it was."""
    user = _user(db)
    try:
        family = families.get_family(db, user.id, family_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Family not found")
    families.ungroup(db, family)
    db.commit()
    return {"ungrouped": True}


@router.post("/{family_id}/members", response_model=schemas.FamilyDashboard)
def add_member(family_id: str, body: schemas.FamilyMemberIn, db: Session = Depends(get_db)):
    user = _user(db)
    try:
        family = families.get_family(db, user.id, family_id)
        families.add_member(db, user.id, family, body.product_id, body.variant_kind)
    except ValueError as exc:
        raise _fail(db, exc)
    db.commit()
    return families.family_dashboard(db, user.id, family)


@router.delete("/{family_id}/members/{product_id}")
def remove_member(family_id: str, product_id: str, db: Session = Depends(get_db)):
    """Take one version out of the family. If only one would be left, the
    family is dissolved (`dissolved: true`)."""
    user = _user(db)
    try:
        family = families.get_family(db, user.id, family_id)
        dissolved = families.remove_member(db, user.id, family, product_id)
    except ValueError as exc:
        raise _fail(db, exc)
    db.commit()
    return {"dissolved": dissolved}
