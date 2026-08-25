from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=Optional[schemas.OrderOut])
def create_order(order_in: schemas.OrderCreate, db: Session = Depends(get_db)):
    """
    Record a checkout attempt. If status='success', this also spawns one
    InventoryItem per unit of quantity (see crud.create_order).

    Dedup happens on the INGESTED MESSAGE, not on the order. That matters:
    a message the user has dismissed (by deleting its order) stays dismissed
    even though no order row exists any more, so re-running a backfill can't
    resurrect it. Re-posting a known message is a safe no-op either way.
    """
    user = crud.get_or_create_default_user(db)
    message = crud.record_message(db, user_id=user.id, order_in=order_in)

    existing = (
        crud.live_orders(db)
        .filter_by(source_id=order_in.source_id, external_id=order_in.external_id)
        .first()
    )
    if existing:
        # A repost is otherwise a no-op, but backfilling a field that's
        # currently NULL is safe and worth doing: it's exactly how a
        # thumbnail_url capture added after the order was first ingested
        # reaches history on the next resync. Anything the user could have
        # edited (status, shipping, notes) is deliberately never touched
        # here -- only fields that started empty and stay retailer/parser
        # -owned move.
        if existing.thumbnail_url is None and order_in.thumbnail_url:
            existing.thumbnail_url = order_in.thumbnail_url
        db.commit()
        return existing

    if message.dismissed_at is not None:
        # Seen before and deliberately deleted. Return a 204 rather than an
        # order body -- there is genuinely nothing to report, and inventing
        # a phantom order would be a lie to the caller.
        db.commit()
        return Response(status_code=204)

    return crud.create_order(db, user_id=user.id, order_in=order_in)


@router.get("", response_model=list[schemas.OrderOut])
def list_orders(
    status: Optional[str] = None,
    source_id: Optional[str] = None,
    retailer: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "date_desc",
    limit: int = 1000,
    db: Session = Depends(get_db),
):
    """
    `status` accepts a comma-separated list ("failed,cancelled") so the UI
    can offer multi-select filters without N round trips.

    NOTE on `limit`: it defaults high on purpose. It used to default to 100
    with the Orders screen asking for 200, which silently truncated the list
    for anyone with more orders than that -- the rows were simply missing
    with nothing to indicate it.
    """
    query = crud.live_orders(db)

    if status:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        if wanted:
            query = query.filter(models.Order.status.in_(wanted))
    if source_id:
        query = query.filter(models.Order.source_id == source_id)
    if retailer:
        query = query.filter(models.Order.retailer == retailer)
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(
            models.Order.raw_product_text.ilike(like)
            | models.Order.order_number.ilike(like)
            | models.Order.retailer.ilike(like)
        )

    # NULLs last on every sort: an order with no price or no number should
    # never outrank real data at the top of the list.
    sorts = {
        "date_desc": models.Order.purchased_at.desc().nullslast(),
        "date_asc": models.Order.purchased_at.asc().nullslast(),
        "price_desc": models.Order.unit_price.desc().nullslast(),
        "price_asc": models.Order.unit_price.asc().nullslast(),
        "product_asc": models.Order.raw_product_text.asc().nullslast(),
        "retailer_asc": models.Order.retailer.asc().nullslast(),
    }
    order_by = sorts.get(sort, sorts["date_desc"])
    return query.order_by(order_by).limit(limit).all()


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
    order. Really deletes them; the source messages are marked dismissed so
    a resync won't bring them back (see crud.delete_orders).
    """
    return schemas.BulkResult(updated=crud.delete_orders(db, body.ids))


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


@router.get("/deleted-summary", response_model=schemas.DeletedSummary)
def deleted_summary(db: Session = Depends(get_db)):
    """What Rebuild would actually bring back."""
    user = crud.get_or_create_default_user(db)
    dismissed = (
        db.query(models.IngestedMessage)
        .filter_by(user_id=user.id)
        .filter(models.IngestedMessage.dismissed_at.isnot(None))
        .all()
    )
    rebuildable = sum(1 for m in dismissed if m.payload)
    return schemas.DeletedSummary(dismissed=len(dismissed), rebuildable=rebuildable)


@router.post("/rebuild", response_model=schemas.RebuildResult)
def rebuild_orders(body: schemas.RebuildRequest, db: Session = Depends(get_db)):
    """
    Bring back orders you deleted, re-created from the payloads Cache
    already stored (IngestedMessage.raw_json). Local and immediate -- it
    does not ask Discord for anything, so it works with the bot stopped.

    Optionally scoped to one source. Safe to re-run: a message that already
    has an order is left alone rather than duplicated.
    """
    user = crud.get_or_create_default_user(db)
    result = crud.rebuild_from_messages(db, user.id, source_id=body.source_id)
    return schemas.RebuildResult(**result)


@router.delete("/{order_id}", status_code=204)
def delete_order(order_id: str, db: Session = Depends(get_db)):
    order = crud.live_orders(db).filter(models.Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    crud.delete_orders(db, [order_id])


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
