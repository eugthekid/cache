"""
crud.py
-------
Database operations that involve more than a single simple insert/select --
kept out of the routers so the business rules live in one place regardless
of which endpoint (or, later, which ingestion source) triggers them.
"""

from sqlalchemy.orm import Session

from app import models, products
from app.models import _now


def live_orders(db: Session):
    """Every read path must go through this rather than db.query(Order)
    directly -- soft-deleted rows still exist (see Order.deleted_at for
    why) and would otherwise show up in lists, counts, and dashboards.
    The ONE deliberate exception is the dedup lookup in POST /orders,
    which must see deleted rows so a resync can't resurrect them."""
    return db.query(models.Order).filter(models.Order.deleted_at.is_(None))


def live_items(db: Session):
    """Inventory equivalent of live_orders()."""
    return db.query(models.InventoryItem).filter(models.InventoryItem.deleted_at.is_(None))


def soft_delete_orders(db: Session, order_ids: list[str]) -> int:
    """Marks orders deleted along with the inventory they spawned. Returns
    how many orders were affected (not counting their units)."""
    if not order_ids:
        return 0
    now = _now()
    db.query(models.InventoryItem).filter(
        models.InventoryItem.order_id.in_(order_ids),
        models.InventoryItem.deleted_at.is_(None),
    ).update({"deleted_at": now}, synchronize_session=False)
    count = (
        db.query(models.Order)
        .filter(models.Order.id.in_(order_ids), models.Order.deleted_at.is_(None))
        .update({"deleted_at": now}, synchronize_session=False)
    )
    db.commit()
    return count


def soft_delete_items(db: Session, item_ids: list[str]) -> int:
    if not item_ids:
        return 0
    count = (
        db.query(models.InventoryItem)
        .filter(
            models.InventoryItem.id.in_(item_ids),
            models.InventoryItem.deleted_at.is_(None),
        )
        .update({"deleted_at": _now()}, synchronize_session=False)
    )
    db.commit()
    return count


def get_or_create_default_user(db: Session) -> models.User:
    """
    Single-user mode for now: there's exactly one local user, created the
    first time the app runs. The desktop app discovers this user's id via
    GET /me rather than hardcoding it, so switching to real accounts later
    doesn't require changing how the client talks to the API.
    """
    user = db.query(models.User).first()
    if user is None:
        user = models.User(email="local@inventory-tracker")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def create_order(db: Session, user_id: str, order_in) -> models.Order:
    """
    Insert an order and, if it's a genuine success, spawn one InventoryItem
    per unit of quantity -- the business rule we designed: only successful
    checkouts ever produce physical inventory to track.
    """
    order = models.Order(user_id=user_id, **order_in.model_dump())

    # Resolve product identity at INGEST, not later: if this only happened
    # in the /products/rebuild batch, every newly-arrived checkout would sit
    # outside the grouped view until someone remembered to re-run it.
    product = products.resolve_product(
        db, user_id, order.raw_product_text, category=order.category
    )
    if product:
        order.product_id = product.id

    db.add(order)
    db.commit()
    db.refresh(order)

    if order.status == "success":
        quantity = order.quantity or 1
        for unit_index in range(1, quantity + 1):
            db.add(
                models.InventoryItem(
                    user_id=user_id,
                    order_id=order.id,
                    unit_index=unit_index,
                    status="in_hand",
                    cost_basis=order.unit_price,
                )
            )
        db.commit()

    return order


def update_order(db: Session, order: models.Order, order_in) -> models.Order:
    """
    Applies only the fields the client actually sent (exclude_unset), so a
    client that's only changing shipping_status doesn't accidentally null
    out everything else it omitted.
    """
    for field, value in order_in.model_dump(exclude_unset=True).items():
        setattr(order, field, value)
    db.commit()
    db.refresh(order)
    return order


def update_inventory_item(
    db: Session, item: models.InventoryItem, item_in
) -> models.InventoryItem:
    """
    Same partial-update pattern as update_order, plus one business rule:
    marking a unit 'sold' without an explicit sold_at fills in "now" --
    the UI's "mark as sold" action shouldn't require a separate date entry
    for the common case of selling something today.
    """
    updates = item_in.model_dump(exclude_unset=True)
    if updates.get("status") == "sold" and "sold_at" not in updates and item.sold_at is None:
        updates["sold_at"] = _now()

    # money_received is exposed to the UI as a checkbox, but stored as a
    # timestamp (see InventoryItem.money_received_at). Translate here so
    # the client never has to invent a date: ticking it means "paid now"
    # unless an explicit date came with it; unticking clears it.
    if "money_received" in updates:
        received = updates.pop("money_received")
        if received and item.money_received_at is None and "money_received_at" not in updates:
            updates["money_received_at"] = _now()
        elif not received:
            updates["money_received_at"] = None

    for field, value in updates.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item
