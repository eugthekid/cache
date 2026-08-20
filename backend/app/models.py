"""
models.py
---------
The SQLAlchemy ORM models -- this is the v1 data model we sketched together:
User -> Source -> Order -> InventoryItem. `products` and `market_prices` are
deliberately NOT here yet; product_id columns will be added via a later
Alembic migration once that phase starts, without touching these tables.

WHY UUID PRIMARY KEYS (not auto-incrementing integers): if this ever becomes
a hosted product serving multiple users, IDs generated on different machines
(e.g. offline-first desktop clients) can never collide, and merging data from
multiple sources is safe. SQLite has no native UUID type, so we store them as
36-character strings and generate them in Python.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """
    A person using the app. Only one row exists today, but every other table
    has a user_id from day one -- retrofitting multi-tenancy later, after
    other tables already exist without it, is much more painful.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    sources: Mapped[list["Source"]] = relationship(back_populates="user")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    inventory_items: Mapped[list["InventoryItem"]] = relationship(back_populates="user")


class Source(Base):
    """
    Where orders come from -- a specific Discord channel, an email account,
    or manual entry. Generalizes "which Discord channel" from
    discord-checkout-tracker into "which ingestion connection, of any kind".
    """
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    # 'discord_channel' | 'email_account' | 'manual'
    type: Mapped[str]
    name: Mapped[str]  # human label, e.g. "hidden-w" or "gmail: eugene@..."

    # Freeform per-type config: {"channel_id": ..., "guild_id": ...} for
    # Discord, {"email": ..., "provider": "gmail"} for email. Stored as JSON
    # rather than dedicated columns because every source type needs
    # different fields, and we'll add source types over time.
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    last_synced_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    user: Mapped["User"] = relationship(back_populates="sources")
    orders: Mapped[list["Order"]] = relationship(back_populates="source")


class Order(Base):
    """
    One row per checkout ATTEMPT -- success, failure, cancellation, or
    pending -- not just successes like discord-checkout-tracker's `checkouts`
    table. `failure_reason` is the same data the Shikari/HayhaAIO "Cancel
    Reason" / "Fraud Reason" fields carry -- there it was used only to REJECT
    a message from being stored; here it's stored as a first-class fact.
    """
    __tablename__ = "orders"
    __table_args__ = (
        # Dedup key: replaces discord-checkout-tracker's "message_id as
        # primary key" trick, generalized to any source type.
        UniqueConstraint("source_id", "external_id", name="uq_orders_source_external_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))

    # The Discord message_id, or an email Message-ID header -- whatever the
    # source uses to uniquely identify this specific notification.
    external_id: Mapped[str]

    # 'success' | 'failed' | 'cancelled' | 'pending'
    status: Mapped[str]
    failure_reason: Mapped[str | None] = mapped_column(default=None)

    # Product matching (phase 2) isn't built yet -- this free-text field is
    # what we actually display/search on on until a `product_id` FK exists.
    raw_product_text: Mapped[str | None] = mapped_column(default=None)

    profile: Mapped[str | None] = mapped_column(default=None)
    site: Mapped[str | None] = mapped_column(default=None)
    module: Mapped[str | None] = mapped_column(default=None)

    quantity: Mapped[int | None] = mapped_column(default=None)
    unit_price: Mapped[float | None] = mapped_column(default=None)
    currency: Mapped[str] = mapped_column(default="USD")

    order_number: Mapped[str | None] = mapped_column(default=None)
    order_url: Mapped[str | None] = mapped_column(default=None)

    # When the checkout actually happened, per the source (e.g. Discord's
    # message timestamp) -- distinct from created_at, which is when WE saw it.
    purchased_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    # Full backup of the original source payload, same purpose as
    # discord-checkout-tracker's raw_json: nothing is ever silently dropped.
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)

    user: Mapped["User"] = relationship(back_populates="orders")
    source: Mapped["Source"] = relationship(back_populates="orders")
    inventory_items: Mapped[list["InventoryItem"]] = relationship(back_populates="order")


class InventoryItem(Base):
    """
    One row per PHYSICAL UNIT you hold -- an order for quantity=2 produces
    two of these. This is the granularity resale actually needs: you might
    sell one unit and keep the other, at different prices, on different
    dates, and per-order tracking can't represent that.

    Business rule enforced in application code, not the schema: only
    orders with status='success' should ever produce inventory_items --
    a failed checkout never had physical goods.
    """
    __tablename__ = "inventory_items"

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    # Nullable so inventory can be added by hand, without a tracked order.
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"), default=None)
    unit_index: Mapped[int | None] = mapped_column(default=None)  # "1 of 2", "2 of 2"

    # 'in_hand' | 'listed' | 'sold' | 'returned' | 'lost'
    status: Mapped[str] = mapped_column(default="in_hand")

    cost_basis: Mapped[float | None] = mapped_column(default=None)
    listed_price: Mapped[float | None] = mapped_column(default=None)
    listed_platform: Mapped[str | None] = mapped_column(default=None)
    sold_price: Mapped[float | None] = mapped_column(default=None)
    sold_at: Mapped[datetime | None] = mapped_column(default=None)
    sold_platform: Mapped[str | None] = mapped_column(default=None)

    notes: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    user: Mapped["User"] = relationship(back_populates="inventory_items")
    order: Mapped["Order | None"] = relationship(back_populates="inventory_items")
