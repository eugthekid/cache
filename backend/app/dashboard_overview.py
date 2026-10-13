"""
dashboard_overview.py
---------------------
The numbers behind the Dashboard screen: profit for a period, a chart of
spending against revenue, profit broken down by category, sales channel and
product, and what's tied up in unsold inventory.

DEFINITIONS (all deliberate):
  - A sale is a unit with status 'sold', a sold_price and a sold_at. It
    belongs to the day it was SOLD, not the day it was bought.
  - Revenue is the sold_price as entered. The user enters what they actually
    received, so it is already net of platform fees -- there is no fee model
    here on purpose (see the roadmap note in the project memory).
  - Profit is revenue minus the unit's cost_basis, which for a unit sold
    through the product screen is the product's average cost.
  - Spent counts every unit still owned or sold, at what was paid for it
    (see product_dashboard.original_cost), on the day it was ordered.
  - Weeks run Monday to Sunday.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app import models
from app.product_dashboard import COUNTED_STATUSES, original_cost

UNSOLD_STAGES = ("in_hand", "in_transit", "not_shipped")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKS_SHOWN = 8
MONTHS_SHOWN = 7
MAX_ALL_TIME_MONTHS = 24
BREAKDOWN_LIMIT = 10


def _day(value: Optional[datetime]) -> Optional[date]:
    return value.date() if value is not None else None


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def month_key(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_label(key: str, today: date) -> str:
    year, month = int(key[:4]), int(key[5:])
    label = _MONTHS[month - 1]
    return label if year == today.year else f"{label} '{str(year)[2:]}"


def _week_label(start: date) -> str:
    return f"{_MONTHS[start.month - 1]} {start.day}"


def _empty_stats() -> dict:
    return {"units": 0, "revenue": 0.0, "cost": 0.0}


def build_overview(db: Session, user_id: str, period: str, today: Optional[date] = None) -> dict:
    today = today or date.today()

    sold_rows = (
        db.query(models.InventoryItem, models.Order)
        .outerjoin(models.Order, models.InventoryItem.order_id == models.Order.id)
        .filter(models.InventoryItem.user_id == user_id)
        .filter(models.InventoryItem.deleted_at.is_(None))
        .filter(models.InventoryItem.status == "sold")
        .filter(models.InventoryItem.sold_price.isnot(None))
        .filter(models.InventoryItem.sold_at.isnot(None))
        .all()
    )
    products = {p.id: p for p in db.query(models.Product).filter_by(user_id=user_id)}

    sales = []
    for item, order in sold_rows:
        product = products.get(item.product_id or (order.product_id if order else None))
        sales.append(
            {
                "day": _day(item.sold_at),
                "revenue": item.sold_price,
                "cost": item.cost_basis or 0.0,
                "category": (product.category if product and product.category else "Uncategorized"),
                "channel": (item.sold_platform or "").strip() or "Unknown",
                "product": (
                    product.canonical_name
                    if product
                    else (item.product_text or (order.raw_product_text if order else None) or "Unknown")
                ),
            }
        )

    held_rows = (
        db.query(models.InventoryItem, models.Order)
        .outerjoin(models.Order, models.InventoryItem.order_id == models.Order.id)
        .filter(models.InventoryItem.user_id == user_id)
        .filter(models.InventoryItem.deleted_at.is_(None))
        .filter(models.InventoryItem.status.in_(COUNTED_STATUSES))
        .all()
    )
    purchases = []  # (day ordered, cost paid, retailer)
    stage_units: dict[str, int] = defaultdict(int)
    stage_cost: dict[str, float] = defaultdict(float)
    for item, order in held_rows:
        cost = original_cost(item, order) or 0.0
        ordered = _day(
            (order.purchased_at or order.created_at) if order is not None else item.created_at
        ) or today
        if order is None:
            retailer = item.retailer or "Added by hand"
        else:
            retailer = order.retailer or "Unknown retailer"
        purchases.append((ordered, cost, retailer))
        if item.status in UNSOLD_STAGES:
            stage_units[item.status] += 1
            stage_cost[item.status] += cost

    this_week = week_start(today)
    this_month = month_key(today)

    def in_period(day: date) -> bool:
        if period == "weekly":
            return week_start(day) == this_week
        if period == "monthly":
            return month_key(day) == this_month
        return True

    period_sales = [s for s in sales if in_period(s["day"])]
    revenue = sum(s["revenue"] for s in period_sales)
    cost = sum(s["cost"] for s in period_sales)
    profit = revenue - cost
    spent = sum(c for d, c, _ in purchases if in_period(d))

    # Chart buckets
    if period == "weekly":
        granularity = "week"
        keys = [(this_week - timedelta(weeks=n)).isoformat() for n in range(WEEKS_SHOWN - 1, -1, -1)]
        bucket_of = lambda d: week_start(d).isoformat()  # noqa: E731
        label_of = lambda k: _week_label(date.fromisoformat(k))  # noqa: E731
        current_key = this_week.isoformat()
    else:
        granularity = "month"
        if period == "monthly":
            count = MONTHS_SHOWN
        else:
            days = [s["day"] for s in sales] + [d for d, _, _ in purchases]
            first = min(days) if days else today
            span = (today.year - first.year) * 12 + (today.month - first.month) + 1
            count = max(1, min(span, MAX_ALL_TIME_MONTHS))
        keys = [month_key(date(*_shift_month(today.year, today.month, -n), 1)) for n in range(count - 1, -1, -1)]
        bucket_of = month_key
        label_of = lambda k: _month_label(k, today)  # noqa: E731
        current_key = this_month

    buckets = {k: {"key": k, "label": label_of(k), "spent": 0.0, "revenue": 0.0, "profit": 0.0, "units": 0, "partial": k == current_key} for k in keys}
    for s in sales:
        b = buckets.get(bucket_of(s["day"]))
        if b:
            b["revenue"] += s["revenue"]
            b["profit"] += s["revenue"] - s["cost"]
            b["units"] += 1
    for d, c, _ in purchases:
        b = buckets.get(bucket_of(d))
        if b:
            b["spent"] += c

    def breakdown(field: str) -> list[dict]:
        groups: dict[str, dict] = defaultdict(_empty_stats)
        for s in period_sales:
            g = groups[s[field]]
            g["units"] += 1
            g["revenue"] += s["revenue"]
            g["cost"] += s["cost"]
        rows = [
            {"name": name, **g, "profit": g["revenue"] - g["cost"]} for name, g in groups.items()
        ]
        rows.sort(key=lambda r: (-r["profit"], r["name"]))
        return rows[:BREAKDOWN_LIMIT]

    spend_by_retailer: dict[str, float] = defaultdict(float)
    for _, c, retailer in purchases:
        spend_by_retailer[retailer] += c

    return {
        "period": period,
        "kpis": {
            "profit": profit,
            "revenue": revenue,
            "cost": cost,
            "spent": spent,
            "units_sold": len(period_sales),
            "roi": (profit / cost) if cost > 0 else None,
            "margin": (profit / revenue) if revenue > 0 else None,
        },
        "chart": {"granularity": granularity, "buckets": [buckets[k] for k in keys]},
        "breakdown": {
            "category": breakdown("category"),
            "channel": breakdown("channel"),
            "product": breakdown("product"),
        },
        "inventory": {
            "units": sum(stage_units.values()),
            "cost": sum(stage_cost.values()),
            "stages": [
                {"stage": stage, "units": stage_units[stage], "cost": stage_cost[stage]}
                for stage in UNSOLD_STAGES
            ],
        },
        "spend_by_retailer": [
            {"name": name, "spent": amount}
            for name, amount in sorted(spend_by_retailer.items(), key=lambda kv: -kv[1])
        ],
    }
