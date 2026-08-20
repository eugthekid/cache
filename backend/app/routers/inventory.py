from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("", response_model=list[schemas.InventoryItemOut])
def list_inventory(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.InventoryItem)
    if status:
        query = query.filter(models.InventoryItem.status == status)
    return query.order_by(models.InventoryItem.created_at.desc()).all()


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
