"""
product_dashboard.py
--------------------
The per-product screen: units broken down by retailer and stage, count
edits typed in by hand, and sales recorded as "N units at $P" instead of
picking individual units.

WHY COUNTS, NOT UNITS: the user doesn't track inventory per order, they
pool it -- "I have 69 of these, all in hand". Units still exist underneath
(one row per physical unit, linked to the order it came from, which is how
a unit knows its retailer), but this screen only ever shows and edits
totals per retailer and stage.

STAGES: a counted unit is order placed (status not_shipped), in transit,
in hand, or sold. A retailer's "in hand / sold" is the last two combined --
which sold unit came from which retailer isn't worth tracking. Units that
are lost or returned, or soft-deleted, aren't counted at all.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app import models
from app.crud import SHIPPABLE_ITEM_STATUSES, _now
from app.retailers import MANUAL_RETAILERS

COUNTED_STATUSES = ("not_shipped", "in_transit", "in_hand", "sold")
_STAGE_RANK = {"not_shipped": 0, "in_transit": 1, "in_hand": 2}

NO_ORDER_LABEL = "Other"


def retailer_label(item: models.InventoryItem, order: Optional[models.Order]) -> str:
    """The store a unit came from: its order's retailer, or, for a unit with
    no order, the one it was added under by hand."""
    if order is None:
        return item.retailer or NO_ORDER_LABEL
    return order.retailer or "Unknown retailer"


def original_cost(item: models.InventoryItem, order: Optional[models.Order]) -> Optional[float]:
    """What the unit cost when bought. A sale overwrites a sold unit's own
    cost_basis with the product average, so the ORDER's price is the
    reliable record of the real purchase price; the unit's own value is the
    fallback for units with no priced order."""
    if order is not None and order.unit_price is not None:
        return order.unit_price
    return item.cost_basis


def _product_units(db: Session, user_id: str, product_id: str) -> list[tuple[models.InventoryItem, Optional[models.Order]]]:
    rows = (
        db.query(models.InventoryItem, models.Order)
        .outerjoin(models.Order, models.InventoryItem.order_id == models.Order.id)
        .filter(models.InventoryItem.user_id == user_id)
        .filter(models.InventoryItem.deleted_at.is_(None))
        .filter(models.InventoryItem.status.in_(COUNTED_STATUSES))
        .filter(
            or_(
                models.InventoryItem.product_id == product_id,
                and_(models.InventoryItem.product_id.is_(None), models.Order.product_id == product_id),
            )
        )
        .all()
    )
    return [(item, order) for item, order in rows]


def average_cost(units) -> Optional[float]:
    costs = [c for item, order in units if (c := original_cost(item, order)) is not None]
    return sum(costs) / len(costs) if costs else None


def build_dashboard(db: Session, user_id: str, product: models.Product) -> dict:
    units = _product_units(db, user_id, product.id)

    retailers: dict[str, dict] = {}
    for item, order in units:
        label = retailer_label(item, order)
        r = retailers.setdefault(
            label,
            {"retailer": label, "units": 0, "order_placed": 0, "in_transit": 0, "in_hand_or_sold": 0, "_prices": []},
        )
        r["units"] += 1
        if item.status == "not_shipped":
            r["order_placed"] += 1
        elif item.status == "in_transit":
            r["in_transit"] += 1
        else:
            r["in_hand_or_sold"] += 1
        cost = original_cost(item, order)
        if cost is not None:
            r["_prices"].append(cost)

    breakdown = []
    for r in sorted(retailers.values(), key=lambda r: (-r["units"], r["retailer"])):
        prices = r.pop("_prices")
        r["avg_unit_price"] = sum(prices) / len(prices) if prices else None
        r["min_unit_price"] = min(prices) if prices else None
        r["max_unit_price"] = max(prices) if prices else None
        breakdown.append(r)

    costs = [c for item, order in units if (c := original_cost(item, order)) is not None]
    sales = (
        db.query(models.Sale)
        .filter_by(user_id=user_id, product_id=product.id)
        .order_by(models.Sale.sold_at.desc(), models.Sale.created_at.desc())
        .all()
    )
    return {
        "product_id": product.id,
        "name": product.canonical_name,
        "category": product.category,
        "total_units": len(units),
        "order_placed": sum(1 for i, _ in units if i.status == "not_shipped"),
        "in_transit": sum(1 for i, _ in units if i.status == "in_transit"),
        "in_hand": sum(1 for i, _ in units if i.status == "in_hand"),
        "sold": sum(1 for i, _ in units if i.status == "sold"),
        "invested": sum(costs),
        "avg_cost": sum(costs) / len(costs) if costs else None,
        "retailers": breakdown,
        # Stores units can still be added for by hand: the fixed list, minus
        # any that already have a card for this product.
        "addable_retailers": [name for name in MANUAL_RETAILERS if name not in retailers],
        "sales": [
            {
                "id": s.id,
                "sold_at": s.sold_at,
                "quantity": s.quantity,
                "unit_price": s.unit_price,
                "unit_cost": s.unit_cost,
                "platform": s.platform,
                "profit": (s.unit_price - s.unit_cost) * s.quantity if s.unit_cost is not None else None,
            }
            for s in sales
        ],
    }


def apply_counts(db: Session, user_id: str, product: models.Product, edits: list[dict]) -> None:
    """
    Make each edited retailer's counts match what the user typed, with the
    fewest changes to the underlying units.

    A retailer's units keep their stage where they can. Stages that hold
    too many give up their surplus; stages that hold too few take from that
    pool, latest stage first, so the units that get REMOVED (a cancelled
    order, a miscount) are the earliest-stage ones. Anything left over is
    soft-deleted; any shortfall is created. Every unit touched is marked
    `manual` so emails and live tracking stop managing it.

    Raises ValueError for counts that can't be honoured (negative, or an
    in-hand/sold count below what's already sold). Nothing is committed
    here.
    """
    units = _product_units(db, user_id, product.id)
    by_retailer: dict[str, list] = {}
    for item, order in units:
        by_retailer.setdefault(retailer_label(item, order), []).append((item, order))

    now = _now()
    for edit in edits:
        label = edit["retailer"]
        placed, transit, hand_or_sold = edit["order_placed"], edit["in_transit"], edit["in_hand_or_sold"]
        if min(placed, transit, hand_or_sold) < 0:
            raise ValueError("Counts can't be negative.")
        typed_price = edit.get("unit_price")
        if typed_price is not None and typed_price < 0:
            raise ValueError("Unit price can't be negative.")

        mine = by_retailer.get(label, [])
        if not mine and label not in MANUAL_RETAILERS:
            raise ValueError(f"{label} isn't a retailer you can add units for.")
        sold = [i for i, _ in mine if i.status == "sold"]
        if hand_or_sold < len(sold):
            raise ValueError(
                f"{label}: in hand / sold can't be lower than the {len(sold)} already recorded as sold."
            )
        desired = {"not_shipped": placed, "in_transit": transit, "in_hand": hand_or_sold - len(sold)}

        current = {stage: [] for stage in desired}
        for item, _ in mine:
            if item.status in current:
                current[item.status].append(item)
        for stage in current:
            current[stage].sort(key=lambda i: (i.created_at, i.unit_index or 0))

        pool: list[models.InventoryItem] = []
        for stage, items in current.items():
            pool.extend(items[desired[stage]:])
        pool.sort(key=lambda i: -_STAGE_RANK[i.status])

        for stage in ("in_hand", "in_transit", "not_shipped"):
            shortfall = desired[stage] - min(len(current[stage]), desired[stage])
            while shortfall > 0 and pool:
                unit = pool.pop(0)
                unit.status = stage
                unit.manual = True
                shortfall -= 1
            for _ in range(shortfall):
                _create_manual_unit(db, user_id, product, mine, label, stage, typed_price)

        for unit in pool:
            unit.deleted_at = now
            unit.manual = True


def _create_manual_unit(db, user_id, product, mine, label: str, stage: str, typed_price: Optional[float] = None) -> None:
    """A unit that has no existing counterpart. Attached to the retailer's
    newest order for this product when there is one, so it keeps that
    retailer and price. With no order to attach to (a store Cache doesn't
    track), it stands alone, tagged with the retailer, and costs the typed
    unit price -- or the average of that retailer's existing units."""
    orders = [o for _, o in mine if o is not None]
    anchor = max(orders, key=lambda o: (o.purchased_at is not None, o.purchased_at or o.id)) if orders else None
    if anchor is None:
        anchor = (
            db.query(models.Order)
            .filter(models.Order.user_id == user_id, models.Order.product_id == product.id)
            .filter(models.Order.status == "success")
            .all()
        )
        anchor = next((o for o in anchor if o.retailer == label), None)

    unit_index = None
    if anchor is not None:
        indices = [
            i.unit_index
            for i in db.query(models.InventoryItem.unit_index).filter(models.InventoryItem.order_id == anchor.id)
            if i.unit_index
        ]
        unit_index = (max(indices) if indices else 0) + 1
    if anchor is not None:
        cost = anchor.unit_price
    elif typed_price is not None:
        cost = typed_price
    else:
        cost = average_cost(mine)
    db.add(
        models.InventoryItem(
            user_id=user_id,
            order_id=anchor.id if anchor else None,
            product_id=None if anchor else product.id,
            retailer=None if anchor else label,
            unit_index=unit_index,
            status=stage,
            cost_basis=cost,
            manual=True,
        )
    )


def record_sale(
    db: Session,
    user_id: str,
    product: models.Product,
    quantity: int,
    unit_price: float,
    platform: Optional[str],
    sold_at: Optional[datetime],
) -> models.Sale:
    """
    Sell `quantity` units out of what's in hand, costed at the product's
    average cost. Which units get marked sold is an implementation detail --
    the ones whose own cost is closest to the average, so replacing their
    cost with the average disturbs total invested the least.
    """
    units = _product_units(db, user_id, product.id)
    in_hand = [(i, o) for i, o in units if i.status == "in_hand"]
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")
    if quantity > len(in_hand):
        raise ValueError(
            f"Only {len(in_hand)} in hand." if in_hand else "There are no units in hand to sell."
        )

    avg = average_cost(units)

    def distance(pair) -> float:
        cost = original_cost(*pair)
        return abs(cost - avg) if cost is not None and avg is not None else 0.0

    chosen = sorted(in_hand, key=lambda p: (distance(p), p[0].created_at))[:quantity]
    when = sold_at or _now()
    item_costs = {}
    for item, _ in chosen:
        item_costs[item.id] = item.cost_basis
        item.status = "sold"
        item.sold_price = unit_price
        item.sold_at = when
        item.sold_platform = platform
        if avg is not None:
            item.cost_basis = avg

    sale = models.Sale(
        user_id=user_id,
        product_id=product.id,
        quantity=quantity,
        unit_price=unit_price,
        unit_cost=avg,
        platform=platform,
        sold_at=when,
        item_costs=item_costs,
    )
    db.add(sale)
    return sale


def undo_sale(db: Session, sale: models.Sale) -> None:
    """Put a sale's units back in hand with their original cost. A unit the
    user has since changed some other way is left as it is."""
    for item_id, cost in (sale.item_costs or {}).items():
        item = db.get(models.InventoryItem, item_id)
        if item is None or item.status != "sold":
            continue
        item.status = "in_hand"
        item.sold_price = None
        item.sold_at = None
        item.sold_platform = None
        item.cost_basis = cost
        # It was in hand when sold; its order may still say "in transit",
        # which the automatic sync would otherwise move it back to.
        item.manual = True
    db.delete(sale)
