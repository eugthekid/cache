"""
crud.py
-------
Database operations that involve more than a single simple insert/select --
kept out of the routers so the business rules live in one place regardless
of which endpoint (or, later, which ingestion source) triggers them.
"""

from sqlalchemy.orm import Session

from app import models


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
