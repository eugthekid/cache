from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=schemas.OrderOut)
def create_order(order_in: schemas.OrderCreate, db: Session = Depends(get_db)):
    """
    Record a checkout attempt. If status='success', this also spawns one
    InventoryItem per unit of quantity (see crud.create_order).

    Dedup: (source_id, external_id) is unique. A repeat POST for the same
    external event (e.g. re-running a backfill) returns the existing order
    unchanged rather than erroring or creating a duplicate -- the same
    "safe to re-run" property discord-checkout-tracker's upsert had.
    """
    existing = (
        db.query(models.Order)
        .filter_by(source_id=order_in.source_id, external_id=order_in.external_id)
        .first()
    )
    if existing:
        return existing

    user = crud.get_or_create_default_user(db)
    return crud.create_order(db, user_id=user.id, order_in=order_in)


@router.get("", response_model=list[schemas.OrderOut])
def list_orders(
    status: Optional[str] = None,
    source_id: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(models.Order)
    if status:
        query = query.filter(models.Order.status == status)
    if source_id:
        query = query.filter(models.Order.source_id == source_id)
    return query.order_by(models.Order.purchased_at.desc()).limit(limit).all()


@router.get("/{order_id}", response_model=schemas.OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter_by(id=order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
