"""
dashboard.py
------------
The aggregation queries behind the Dashboard screen's charts and widgets --
distinct from routers/inventory.py's `/inventory/summary`, which owns the
five KPI cards. Each endpoint here backs one specific chart/widget from the
design: monthly spend/revenue (the line chart), aging buckets ("how long
you've held it"), and the retailer/category breakdowns (that widget's other
two dropdown views).
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# SQLite has no native month-bucket function; strftime('%Y-%m', ...) is the
# standard way to get one. coalesce(purchased_at, created_at) means a
# manually-entered order with no purchased_at set still lands in a real
# month instead of silently dropping out of the chart.
_MONTH = func.strftime("%Y-%m", func.coalesce(models.Order.purchased_at, models.Order.created_at))
_SOLD_MONTH = func.strftime("%Y-%m", models.InventoryItem.sold_at)


@router.get("/monthly")
def spend_and_revenue_by_month(months: int = Query(default=6, ge=1, le=36), db: Session = Depends(get_db)):
    """
    One row per month: spend (successful orders, by purchase date) and
    revenue (sold units, by sale date). Two independent GROUP BYs merged
    in Python rather than one query with a join, because they're keyed by
    different dates on different tables -- forcing them into one query
    would mean an outer join that double-counts or drops rows depending on
    which side has more months represented.
    """
    since = datetime.now(timezone.utc) - timedelta(days=31 * months)

    spend_rows = (
        db.query(_MONTH.label("month"), func.sum(models.Order.unit_price * models.Order.quantity))
        .filter(models.Order.deleted_at.is_(None))
        .filter(models.Order.status == "success")
        .filter(func.coalesce(models.Order.purchased_at, models.Order.created_at) >= since)
        .group_by("month")
        .all()
    )
    revenue_rows = (
        db.query(_SOLD_MONTH.label("month"), func.sum(models.InventoryItem.sold_price))
        .filter(models.InventoryItem.deleted_at.is_(None))
        .filter(models.InventoryItem.status == "sold")
        .filter(models.InventoryItem.sold_at >= since)
        .group_by("month")
        .all()
    )

    by_month: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "revenue": 0.0})
    for month, total in spend_rows:
        if month:
            by_month[month]["spend"] = float(total or 0)
    for month, total in revenue_rows:
        if month:
            by_month[month]["revenue"] = float(total or 0)

    return [
        {"month": month, "spend": v["spend"], "revenue": v["revenue"]}
        for month, v in sorted(by_month.items())
    ]


@router.get("/aging")
def inventory_aging(db: Session = Depends(get_db)):
    """
    Buckets every unsold unit (in_hand or listed) by days since it entered
    inventory, matching the "How long you've held it" widget. Bucketed on
    created_at, not purchased_at: created_at is when the physical unit
    itself started existing in this system (including imported stock with
    no order behind it, where purchased_at doesn't even apply).
    """
    items = (
        crud.live_items(db)
        .filter(models.InventoryItem.status.in_(["in_hand", "listed"]))
        .all()
    )
    now = datetime.now(timezone.utc)

    buckets = [
        {"label": "0-7d", "min_days": 0, "max_days": 7, "count": 0},
        {"label": "8-30d", "min_days": 8, "max_days": 30, "count": 0},
        {"label": "31-60d", "min_days": 31, "max_days": 60, "count": 0},
        {"label": "60d+", "min_days": 61, "max_days": None, "count": 0},
    ]
    value_tied_up_60d_plus = 0.0

    for item in items:
        created_at = item.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (now - created_at).days

        if age_days <= 7:
            buckets[0]["count"] += 1
        elif age_days <= 30:
            buckets[1]["count"] += 1
        elif age_days <= 60:
            buckets[2]["count"] += 1
        else:
            buckets[3]["count"] += 1
            value_tied_up_60d_plus += item.cost_basis or 0

    return {"buckets": buckets, "value_tied_up_60d_plus": value_tied_up_60d_plus}


@router.get("/by-retailer")
def orders_by_retailer(db: Session = Depends(get_db)):
    """Order counts grouped by site, most-orders first -- nulls excluded
    since 'unknown site' isn't a retailer to compare against."""
    rows = (
        db.query(models.Order.site, func.count(models.Order.id))
        .filter(models.Order.deleted_at.is_(None))
        .filter(models.Order.site.isnot(None))
        .group_by(models.Order.site)
        .order_by(func.count(models.Order.id).desc())
        .all()
    )
    return [{"site": site, "order_count": count} for site, count in rows]


@router.get("/by-category")
def inventory_by_category(db: Session = Depends(get_db)):
    """
    Unit count / spend / realized profit grouped by the order's category.
    Joins inventory_items -> orders, so a unit added by hand with no
    order_id (see docs/DATA-MODEL.md on why order_id is nullable) has no
    category to group by and is deliberately excluded here, not lumped
    into an "Uncategorized" bucket that would be misleading either way.
    """
    profit_if_sold = case(
        (
            models.InventoryItem.status == "sold",
            func.coalesce(models.InventoryItem.sold_price, 0)
            - func.coalesce(models.InventoryItem.cost_basis, 0),
        ),
        else_=0,
    )
    rows = (
        db.query(
            models.Order.category,
            func.count(models.InventoryItem.id),
            func.sum(models.InventoryItem.cost_basis),
            func.sum(profit_if_sold),
        )
        .join(models.Order, models.InventoryItem.order_id == models.Order.id)
        .filter(models.InventoryItem.deleted_at.is_(None))
        .filter(models.Order.deleted_at.is_(None))
        .filter(models.Order.category.isnot(None))
        .group_by(models.Order.category)
        .order_by(func.count(models.InventoryItem.id).desc())
        .all()
    )
    return [
        {
            "category": category,
            "unit_count": unit_count,
            "total_spend": float(total_spend or 0),
            "total_profit": float(total_profit or 0),
        }
        for category, unit_count, total_spend, total_profit in rows
    ]
