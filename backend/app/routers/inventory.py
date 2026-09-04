from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, schemas
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
    items = [
        models.InventoryItem(
            user_id=user.id,
            order_id=None,
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
    actually still held (in_hand/listed), not sold/returned/lost ones.
    """
    items = crud.live_items(db).all()
    unsold_statuses = {"in_hand", "listed"}
    return {
        "total_units": len(items),
        "in_hand": sum(1 for i in items if i.status == "in_hand"),
        "listed": sum(1 for i in items if i.status == "listed"),
        "sold": sum(1 for i in items if i.status == "sold"),
        "total_cost_basis": sum(i.cost_basis or 0 for i in items),
        "total_sold_revenue": sum(i.sold_price or 0 for i in items if i.status == "sold"),
        "est_inventory_value": sum(
            i.cost_basis or 0 for i in items if i.status in unsold_statuses
        ),
        "order_count": crud.live_orders(db).count(),
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
