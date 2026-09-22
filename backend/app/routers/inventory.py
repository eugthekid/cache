from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, products, schemas
from app.database import get_db

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("", response_model=list[schemas.InventoryItemOut])
def list_inventory(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = crud.live_items(db)
    if status:
        query = query.filter(models.InventoryItem.status == status)
    return query.order_by(models.InventoryItem.created_at.desc()).all()


@router.post("", response_model=list[schemas.InventoryItemOut])
def create_inventory_items(body: schemas.InventoryItemCreate, db: Session = Depends(get_db)):
    """One-off manual add -- see schemas.InventoryItemCreate. `quantity` >
    1 spawns that many identical standalone units in one call, same as
    typing the same spreadsheet row N times would."""
    if body.quantity < 1:
        raise HTTPException(status_code=400, detail="quantity must be at least 1")
    user = crud.get_or_create_default_user(db)
    # Same resolution materialize_order() gives an order-linked item --
    # without a real Product row, a manually-added item never enters the
    # catalog-matching pipeline: no clean name, no image, ever. See the
    # identical fix and comment in routers/import_.py's mode='unit' path.
    product = products.resolve_product(db, user.id, body.product_text)
    items = [
        models.InventoryItem(
            user_id=user.id,
            order_id=None,
            product_id=product.id if product else None,
            status=body.status,
            product_text=body.product_text,
            cost_basis=body.cost_basis,
            location=body.location,
            notes=body.notes,
        )
        for _ in range(body.quantity)
    ]
    db.add_all(items)
    db.commit()
    for item in items:
        db.refresh(item)
    return items


# NOTE: literal-path routes (like /summary below) must be registered BEFORE
# any /{item_id}-style route on the same router. FastAPI/Starlette matches
# in registration order, so a /{item_id} route defined first will greedily
# swallow "summary" as if it were an id -- this bit us once already; keep
# every new literal path above this comment, not below it.
@router.get("/summary")
def inventory_summary(db: Session = Depends(get_db)):
    """
    Quick spend/value rollup -- the kind of number a dashboard's top line
    would show. Deliberately simple (Python-side aggregation, not raw SQL)
    since this is a scaffold; worth moving to a SQL GROUP BY if this ever
    needs to run over a large inventory.

    `total_cost_basis` is the cost of everything you HOLD OR HELD, which is
    deliberately NOT the same number as /dashboard/monthly's spend. It used
    to be -- when every unit came from an order, summing cost_basis equalled
    summing unit_price*quantity over success orders. Spreadsheet import
    broke that equivalence by adding units with order_id=NULL (stock you
    already owned, never bought through a tracked order), and those units
    have a real cost basis but no purchase to attribute it to. Don't
    "reconcile" these two numbers; they answer different questions.
    `est_inventory_value` is narrower still: only cost_basis for units
    actually still held or on the way (not_shipped/in_transit/in_hand --
    see crud.SHIPPABLE_ITEM_STATUSES), not sold/returned/lost ones.
    """
    items = crud.live_items(db).all()
    unsold_statuses = crud.SHIPPABLE_ITEM_STATUSES

    # PRICED sold units only, matching how /products/grouped computes
    # avg_sale_price and total_profit: a unit marked sold without a
    # recorded price can't contribute to revenue, profit or ROI without
    # silently dragging every average toward zero.
    sold_priced = [i for i in items if i.status == "sold" and i.sold_price is not None]
    sold_revenue = sum(i.sold_price for i in sold_priced)
    sold_cost_basis = sum(i.cost_basis or 0 for i in sold_priced)

    return {
        "total_units": len(items),
        "not_shipped": sum(1 for i in items if i.status == "not_shipped"),
        "in_transit": sum(1 for i in items if i.status == "in_transit"),
        "in_hand": sum(1 for i in items if i.status == "in_hand"),
        "sold": sum(1 for i in items if i.status == "sold"),
        "total_cost_basis": sum(i.cost_basis or 0 for i in items),
        # 0-inclusive, kept as-is for existing callers.
        "total_sold_revenue": sum(i.sold_price or 0 for i in items if i.status == "sold"),
        "est_inventory_value": sum(
            i.cost_basis or 0 for i in items if i.status in unsold_statuses
        ),
        "order_count": crud.live_orders(db).count(),
        # Realized-sale rollups for the Dashboard's Sales panel.
        "sold_priced_count": len(sold_priced),
        "sold_revenue": sold_revenue,
        "sold_cost_basis": sold_cost_basis,
        "realized_profit": sold_revenue - sold_cost_basis,
    }


@router.post("/bulk-delete", response_model=schemas.BulkResult)
def bulk_delete_inventory(body: schemas.BulkIds, db: Session = Depends(get_db)):
    """
    Deletes only the inventory_item rows themselves -- never the order they
    came from. Removing a unit here is "I don't actually have this / this
    was a data-entry mistake," not "undo the purchase" (that's bulk-delete
    on the Orders side, which does cascade).
    """
    return schemas.BulkResult(updated=crud.soft_delete_items(db, body.ids))


@router.post("/bulk-status", response_model=schemas.BulkResult)
def bulk_update_inventory_status(
    body: schemas.BulkInventoryStatusUpdate, db: Session = Depends(get_db)
):
    if not body.ids:
        return schemas.BulkResult(updated=0)
    updated = (
        crud.live_items(db)
        .filter(models.InventoryItem.id.in_(body.ids))
        .update({"status": body.status}, synchronize_session=False)
    )
    db.commit()
    return schemas.BulkResult(updated=updated)


@router.post("/bulk-edit", response_model=schemas.BulkResult)
def bulk_edit_items(body: schemas.InventoryBulkUpdate, db: Session = Depends(get_db)):
    """
    Mass-adjust price/location/platform/etc. across a selection. Loops
    and reuses crud.update_inventory_item per item -- NOT a single bulk
    SQL UPDATE -- because that function carries a real business rule
    (marking 'sold' without a date fills in today) that a bare column
    assignment can't replicate. Same tradeoff already made for bulk
    order-status (see routers/orders.py's bulk_update_order_status).
    """
    if not body.ids:
        return schemas.BulkResult(updated=0)
    patch = schemas.InventoryItemUpdate(**body.model_dump(exclude_unset=True, exclude={"ids"}))
    items = crud.live_items(db).filter(models.InventoryItem.id.in_(body.ids)).all()
    for item in items:
        crud.update_inventory_item(db, item, patch)
    return schemas.BulkResult(updated=len(items))


@router.post("/bulk-duplicate", response_model=list[schemas.InventoryItemOut])
def bulk_duplicate_items(body: schemas.BulkIds, db: Session = Depends(get_db)):
    """
    "I have another one of these" -- clones cost basis, location and notes
    from each source unit, but deliberately NOT its status or sale fields:
    a duplicate is fresh stock, not a copy of a completed sale, so it
    always starts 'in_hand' with sold_price/listed_price left null even
    when the original was sold.

    Detached from the original's order (order_id always null on the
    result) rather than pointed at the same order -- a duplicate wasn't
    part of that purchase, and attaching it would silently inflate that
    order's own unit count. product_id is carried forward explicitly
    (falling back to the order's, for a unit that only has one via its
    order) so the copy still lands in the same product group instead of
    becoming a second "Unmatched" bucket for the same item.
    """
    if not body.ids:
        return []
    rows = (
        crud.live_items(db)
        .filter(models.InventoryItem.id.in_(body.ids))
        .all()
    )
    order_product_ids = dict(
        db.query(models.Order.id, models.Order.product_id).filter(
            models.Order.id.in_({r.order_id for r in rows if r.order_id})
        )
    )
    user = crud.get_or_create_default_user(db)
    created = [
        models.InventoryItem(
            user_id=user.id,
            order_id=None,
            product_id=item.product_id or order_product_ids.get(item.order_id),
            product_text=item.product_text,
            status="in_hand",
            cost_basis=item.cost_basis,
            location=item.location,
            notes=item.notes,
        )
        for item in rows
    ]
    db.add_all(created)
    db.commit()
    for item in created:
        db.refresh(item)
    return created


@router.post("/restore", response_model=schemas.BulkResult)
def restore_inventory(body: schemas.BulkIds, db: Session = Depends(get_db)):
    """Undo a delete of a STANDALONE unit (one imported directly in
    inventory mode, with no order behind it). Units belonging to an order
    are hard deleted with it and come back via POST /orders/rebuild
    instead -- see InventoryItem.deleted_at."""
    if not body.ids:
        return schemas.BulkResult(updated=0)
    restored = (
        db.query(models.InventoryItem)
        .filter(models.InventoryItem.id.in_(body.ids))
        .update({"deleted_at": None}, synchronize_session=False)
    )
    db.commit()
    return schemas.BulkResult(updated=restored)


@router.delete("/{item_id}", status_code=204)
def delete_inventory_item(item_id: str, db: Session = Depends(get_db)):
    item = crud.live_items(db).filter(models.InventoryItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    crud.soft_delete_items(db, [item_id])


@router.get("/{item_id}", response_model=schemas.InventoryItemOut)
def get_inventory_item(item_id: str, db: Session = Depends(get_db)):
    item = crud.live_items(db).filter(models.InventoryItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return item


@router.patch("/{item_id}", response_model=schemas.InventoryItemOut)
def update_inventory_item(
    item_id: str, item_in: schemas.InventoryItemUpdate, db: Session = Depends(get_db)
):
    """
    The endpoint the Inventory detail panel's "Save changes" actually calls
    -- marking something listed/sold/returned, editing cost basis, setting
    a sale price and platform. See crud.update_inventory_item for the one
    business rule attached: marking 'sold' fills in sold_at if omitted.
    """
    item = crud.live_items(db).filter(models.InventoryItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return crud.update_inventory_item(db, item, item_in)
