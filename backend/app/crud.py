"""
crud.py
-------
Database operations that involve more than a single simple insert/select --
kept out of the routers so the business rules live in one place regardless
of which endpoint (or, later, which ingestion source) triggers them.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from typing import Optional

from app import models, products, retailers, tracking
from app.models import _now


def live_orders(db: Session):
    """All orders. Kept as a named helper (rather than inlining
    db.query(Order) at ~10 call sites) because orders were soft-deleted
    until recently and every read path had to filter tombstones out. They
    are hard deleted now -- see IngestedMessage -- so there is nothing left
    to filter, and this exists so that stays true in one place."""
    return db.query(models.Order)


def live_items(db: Session):
    """Inventory equivalent of live_orders()."""
    return db.query(models.InventoryItem).filter(models.InventoryItem.deleted_at.is_(None))


def delete_orders(db: Session, order_ids: list[str]) -> int:
    """
    Really deletes orders and the units they spawned, and marks their
    source messages dismissed so a resync doesn't just bring them back.

    Those two halves are the whole design: the hard delete is what keeps
    the user's orders table honest (no hidden rows), and the dismissal is
    what makes the delete survive the next sync. Undoing it is
    rebuild_from_messages(), which clears the dismissal and re-materializes
    from the stored payload -- no Discord round-trip needed.
    """
    if not order_ids:
        return 0

    # Read the (source_id, external_id) pairs BEFORE deleting the rows that
    # carry them -- afterwards there is nothing left to look them up by.
    keys = (
        db.query(models.Order.source_id, models.Order.external_id)
        .filter(models.Order.id.in_(order_ids))
        .all()
    )
    now = _now()
    for source_id, external_id in keys:
        db.query(models.IngestedMessage).filter_by(
            source_id=source_id, external_id=external_id
        ).update({"dismissed_at": now}, synchronize_session=False)

    db.query(models.InventoryItem).filter(
        models.InventoryItem.order_id.in_(order_ids)
    ).delete(synchronize_session=False)
    count = (
        db.query(models.Order)
        .filter(models.Order.id.in_(order_ids))
        .delete(synchronize_session=False)
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


def _jsonable(data: dict) -> dict:
    """datetimes -> ISO strings, so the payload round-trips through the JSON
    column and back into OrderCreate unchanged."""
    return {
        k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in data.items()
    }


def record_message(db: Session, user_id: str, order_in) -> models.IngestedMessage:
    """
    Upsert the "we have seen this" record for an incoming payload. This is
    the sync dedup key now -- it survives the order being deleted, which is
    exactly what stops a resync from recreating something you removed.
    """
    message = (
        db.query(models.IngestedMessage)
        .filter_by(source_id=order_in.source_id, external_id=order_in.external_id)
        .first()
    )
    if message is None:
        message = models.IngestedMessage(
            user_id=user_id,
            source_id=order_in.source_id,
            external_id=order_in.external_id,
            # The ENTIRE inbound payload, not just order_in.raw_json --
            # status and friends are derived upstream and exist nowhere
            # else. See IngestedMessage.payload.
            payload=_jsonable(order_in.model_dump()),
            occurred_at=order_in.purchased_at,
        )
        db.add(message)
        db.flush()
    return message


def materialize_order(db: Session, user_id: str, order_in) -> models.Order:
    """
    Build the Order (and its inventory units) from a payload. Split out of
    create_order so a rebuild can re-run exactly the same construction from
    a stored message, rather than duplicating the business rules.
    """
    order = models.Order(user_id=user_id, **order_in.model_dump())

    # Normalize at INGEST so history and new arrivals are always consistent.
    # Both derivations keep the original: `site` is untouched beside
    # `retailer`, and the uncleaned product text stays in the stored payload.
    order.retailer = retailers.display_name(order.site)
    if order.raw_product_text:
        order.raw_product_text = products.display_name(order.raw_product_text)

    # Resolve product identity at INGEST, not later: if this only happened
    # in the /products/rebuild batch, every newly-arrived checkout would sit
    # outside the grouped view until someone remembered to re-run it.
    product = products.resolve_product(
        db, user_id, order.raw_product_text, category=order.category
    )
    if product:
        order.product_id = product.id

    # Same reasoning as the two derivations above: do it at ingest so a
    # tracking number arriving from Discord or a spreadsheet already knows
    # its carrier, instead of only the ones typed in by hand.
    sync_tracking_fields(order)

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


def create_order(db: Session, user_id: str, order_in) -> models.Order:
    """
    Insert an order and, if it's a genuine success, spawn one InventoryItem
    per unit of quantity -- the business rule we designed: only successful
    checkouts ever produce physical inventory to track.
    """
    return materialize_order(db, user_id, order_in)


def sync_tracking_fields(order: models.Order, previous_shipping_status: Optional[str] = None) -> None:
    """
    Keeps the derived shipping fields consistent with what was just set.

    Two jobs, both cheap and offline:
      * fill in `carrier` from the tracking number's format, whenever the
        number is present and the carrier isn't already known;
      * raise a shipping alert when the status ENTERS 'delivered' or
        'exception'.

    The alert is edge-triggered on a real transition, not on the current
    value: re-saving an order that was already delivered shouldn't push a
    duplicate "delivered!" notification the user has to dismiss again.
    """
    number = tracking.normalize_tracking_number(order.tracking_number)
    order.tracking_number = number
    if number and not order.carrier:
        order.carrier = tracking.detect_carrier(number)
    if not number:
        order.carrier = None

    alerting = {"delivered", "exception"}
    entered = order.shipping_status in alerting and previous_shipping_status not in alerting
    if entered:
        order.shipping_alert_at = _now()
        order.shipping_alert_seen_at = None
    elif order.shipping_status not in alerting:
        # Moved back out of an alerting state (a correction, or a package
        # that resumed transit after an exception) -- the alert no longer
        # describes reality, so it shouldn't keep sitting in the feed.
        order.shipping_alert_at = None
        order.shipping_alert_seen_at = None


def reconcile_order_inventory(db: Session, order: models.Order) -> None:
    """
    Keeps an order's inventory units consistent with its status AFTER the
    order was first ingested.

    materialize_order() only creates units at INGEST time, gated on
    status == 'success' at that moment -- it has no way to react to a
    LATER status edit, whether that's the user correcting a mistake or a
    bulk status change. Without this, an order edited to 'cancelled' after
    its units were already created keeps them forever (confirmed live:
    two Discord orders retailer-cancelled after the fact were still
    holding 4 phantom units), and an order corrected the other way, INTO
    'success', never gets any.

    Conservative on purpose: only touches units still 'in_hand'. A unit
    that's been listed or sold is a real action the user took -- it must
    never be silently deleted just because an order's status changed
    later, whatever the retailer says about the order itself. Soft
    delete, not hard: the order isn't being deleted, just re-classified,
    and a status corrected back to 'success' should un-cancel cleanly.
    """
    live_items = (
        db.query(models.InventoryItem)
        .filter(models.InventoryItem.order_id == order.id)
        .filter(models.InventoryItem.deleted_at.is_(None))
        .all()
    )
    if order.status == "success":
        if not live_items:
            quantity = order.quantity or 1
            for unit_index in range(1, quantity + 1):
                db.add(
                    models.InventoryItem(
                        user_id=order.user_id,
                        order_id=order.id,
                        unit_index=unit_index,
                        status="in_hand",
                        cost_basis=order.unit_price,
                    )
                )
    else:
        now = _now()
        for item in live_items:
            if item.status == "in_hand":
                item.deleted_at = now


def update_order(db: Session, order: models.Order, order_in) -> models.Order:
    """
    Applies only the fields the client actually sent (exclude_unset), so a
    client that's only changing shipping_status doesn't accidentally null
    out everything else it omitted.
    """
    previous_shipping_status = order.shipping_status
    for field, value in order_in.model_dump(exclude_unset=True).items():
        setattr(order, field, value)
    sync_tracking_fields(order, previous_shipping_status)
    # Status is one of the fields this may have just changed -- reconcile
    # unconditionally rather than diffing old-vs-new: it's cheap (one
    # indexed query when nothing needs to change) and idempotent, so
    # there's no benefit to only calling it on an actual transition.
    reconcile_order_inventory(db, order)
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


def rebuild_from_messages(
    db: Session, user_id: str, source_id: str | None = None
) -> dict:
    """
    Undo deletions by re-creating orders from the messages we already
    stored -- the counterpart to delete_orders().

    This is a LOCAL operation. Because IngestedMessage keeps the payload,
    nothing here touches Discord: no re-walking channels, no rate limits,
    no waiting on a bot to be running. That is the main practical payoff of
    splitting messages from orders.

    Only messages that are dismissed AND have no order are rebuilt, so this
    is safe to run repeatedly and can never duplicate a live order.
    Restricted to one source when `source_id` is given.
    """
    from app import schemas  # local import: schemas imports nothing from crud

    query = db.query(models.IngestedMessage).filter(
        models.IngestedMessage.user_id == user_id,
        models.IngestedMessage.dismissed_at.isnot(None),
    )
    if source_id:
        query = query.filter(models.IngestedMessage.source_id == source_id)

    existing_keys = {
        (o.source_id, o.external_id)
        for o in db.query(models.Order.source_id, models.Order.external_id).all()
    }

    rebuilt = 0
    skipped = 0
    for message in query.all():
        if (message.source_id, message.external_id) in existing_keys:
            # An order already exists for this message -- clear the stale
            # dismissal but don't build a second one.
            message.dismissed_at = None
            skipped += 1
            continue

        payload = message.payload or {}
        if not payload:
            # Nothing stored to rebuild from (rows that predate payload
            # capture). Leave it dismissed rather than inventing an order.
            skipped += 1
            continue

        # The payload IS an OrderCreate -- rebuild is a replay, not a
        # re-derivation, so a rebuilt order is identical to the original
        # rather than a best-effort reconstruction of it.
        order_in = schemas.OrderCreate(**payload)
        materialize_order(db, user_id, order_in)
        message.dismissed_at = None
        rebuilt += 1

    db.commit()
    return {"rebuilt": rebuilt, "skipped": skipped}
