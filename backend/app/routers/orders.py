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
    # Deliberately NOT crud.live_orders(): this lookup must see soft-deleted
    # rows too. The bot re-walks a channel's entire history on every restart,
    # so if a deleted order were invisible here it would be re-created every
    # single resync -- "I deleted this" has to survive that.
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
    query = crud.live_orders(db)
    if status:
        query = query.filter(models.Order.status == status)
    if source_id:
        query = query.filter(models.Order.source_id == source_id)
    return query.order_by(models.Order.purchased_at.desc()).limit(limit).all()


# NOTE: literal-path routes (bulk-delete, bulk-status) must stay above
# /{order_id} -- see inventory.py's identical note; this bit us there once
# already and the fix is the same rule here.
@router.post("/bulk-delete", response_model=schemas.BulkResult)
def bulk_delete_orders(body: schemas.BulkIds, db: Session = Depends(get_db)):
    """
    Soft-deletes each order AND every inventory_item it spawned -- an
    order's units only exist because that order happened, so undoing the
    order undoes them too. Does not touch inventory_items with
    order_id=NULL (imported/standalone stock), which were never tied to an
    order. See Order.deleted_at for why this is a soft delete.
    """
    return schemas.BulkResult(updated=crud.soft_delete_orders(db, body.ids))


@router.post("/bulk-status", response_model=schemas.BulkResult)
def bulk_update_order_status(body: schemas.BulkOrderStatusUpdate, db: Session = Depends(get_db)):
    if not body.ids:
        return schemas.BulkResult(updated=0)
    updated = (
        crud.live_orders(db)
        .filter(models.Order.id.in_(body.ids))
        .update({"status": body.status}, synchronize_session=False)
    )
    db.commit()
    return schemas.BulkResult(updated=updated)


@router.post("/restore", response_model=schemas.BulkResult)
def restore_orders(body: schemas.BulkIds, db: Session = Depends(get_db)):
    """Undo a delete. Soft deletion is what makes this possible at all --
    with a hard DELETE the row (and its units) would simply be gone."""
    if not body.ids:
        return schemas.BulkResult(updated=0)
    db.query(models.InventoryItem).filter(models.InventoryItem.order_id.in_(body.ids)).update(
        {"deleted_at": None}, synchronize_session=False
    )
    restored = (
        db.query(models.Order)
        .filter(models.Order.id.in_(body.ids))
        .update({"deleted_at": None}, synchronize_session=False)
    )
    db.commit()
    return schemas.BulkResult(updated=restored)


@router.delete("/{order_id}", status_code=204)
def delete_order(order_id: str, db: Session = Depends(get_db)):
    order = crud.live_orders(db).filter(models.Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    crud.soft_delete_orders(db, [order_id])


@router.get("/{order_id}", response_model=schemas.OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = crud.live_orders(db).filter(models.Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/{order_id}", response_model=schemas.OrderOut)
def update_order(order_id: str, order_in: schemas.OrderUpdate, db: Session = Depends(get_db)):
    """
    Edits an existing order -- correcting a typo, updating shipping status
    as a package moves, changing status/failure_reason by hand. Does NOT
    retroactively spawn or remove inventory_items if status changes to/from
    'success' after the fact; that's a deliberate v1 limitation, not an
    oversight -- see the note in docs/DATA-MODEL.md if that ever needs to
    change.
    """
    order = crud.live_orders(db).filter(models.Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return crud.update_order(db, order, order_in)
