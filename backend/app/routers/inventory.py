from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("", response_model=list[schemas.InventoryItemOut])
def list_inventory(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.InventoryItem)
    if status:
        query = query.filter(models.InventoryItem.status == status)
    return query.order_by(models.InventoryItem.created_at.desc()).all()


@router.get("/{item_id}", response_model=schemas.InventoryItemOut)
def get_inventory_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(models.InventoryItem).filter_by(id=item_id).first()
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
    item = db.query(models.InventoryItem).filter_by(id=item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return crud.update_inventory_item(db, item, item_in)


@router.get("/summary")
def inventory_summary(db: Session = Depends(get_db)):
    """
    Quick spend/value rollup -- the kind of number a dashboard's top line
    would show. Deliberately simple (Python-side aggregation, not raw SQL)
    since this is a scaffold; worth moving to a SQL GROUP BY if this ever
    needs to run over a large inventory.
    """
    items = db.query(models.InventoryItem).all()
    return {
        "total_units": len(items),
        "in_hand": sum(1 for i in items if i.status == "in_hand"),
        "listed": sum(1 for i in items if i.status == "listed"),
        "sold": sum(1 for i in items if i.status == "sold"),
        "total_cost_basis": sum(i.cost_basis or 0 for i in items),
        "total_sold_revenue": sum(i.sold_price or 0 for i in items if i.status == "sold"),
    }
