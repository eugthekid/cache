"""
models.py
---------
The SQLAlchemy ORM models. Core shape: User -> Source -> Order ->
InventoryItem, with Product/ProductAlias sitting alongside as the identity
layer that answers "are these two rows the same thing?" across sources.
`market_prices` is still deliberately absent -- that's v2.

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
    app_settings: Mapped[list["AppSetting"]] = relationship(back_populates="user")


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

    # The raw name exactly as the source reported it -- never rewritten, so
    # the original is always recoverable and new alias rules can be re-run
    # over history. `product_id` is the resolved identity (see Product).
    raw_product_text: Mapped[str | None] = mapped_column(default=None)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), default=None)

    profile: Mapped[str | None] = mapped_column(default=None)

    # `site` is whatever the source said -- a URL from one bot, a bare name
    # from another. `retailer` is the normalized identity derived from it
    # (see retailers.py), which is what the UI groups, filters and displays
    # on. Keeping both means the original is never lost and the rules can
    # be re-run over history if they improve.
    site: Mapped[str | None] = mapped_column(default=None)
    retailer: Mapped[str | None] = mapped_column(default=None)
    module: Mapped[str | None] = mapped_column(default=None)

    # Free text, same as `site`/`profile` -- NOT a foreign key into a
    # category table. Real product matching is deferred to v2 (see
    # `products` below); this exists only so the dashboard's by-category
    # breakdown has something real to group by in the meantime, set by
    # hand or guessed by the Discord/import ingestion layer.
    category: Mapped[str | None] = mapped_column(default=None)

    quantity: Mapped[int | None] = mapped_column(default=None)
    unit_price: Mapped[float | None] = mapped_column(default=None)
    currency: Mapped[str] = mapped_column(default="USD")

    order_number: Mapped[str | None] = mapped_column(default=None)
    order_url: Mapped[str | None] = mapped_column(default=None)

    # Deliberately separate from `status`: a checkout can succeed while the
    # package is still in transit, and a failed/cancelled order simply never
    # progresses past 'not_shipped' -- one combined enum can't represent
    # "succeeded but not yet delivered".
    # 'not_shipped' | 'label_created' | 'in_transit' | 'delivered' | 'exception'
    shipping_status: Mapped[str] = mapped_column(default="not_shipped")
    tracking_number: Mapped[str | None] = mapped_column(default=None)

    # Denormalized on purpose for now: a short label a list column can show
    # ("Home", "Apt 4C") plus the full address as text. Worth its own table
    # once addresses are reused enough to be worth managing separately --
    # not yet (see docs/DATA-MODEL.md).
    ship_to_label: Mapped[str | None] = mapped_column(default=None)
    ship_to_address: Mapped[str | None] = mapped_column(default=None)

    # When the checkout actually happened, per the source (e.g. Discord's
    # message timestamp) -- distinct from created_at, which is when WE saw it.
    purchased_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    # NOTE: there is deliberately no `deleted_at` here. Orders are HARD
    # deleted -- what you see in the table is what exists. The job that
    # column used to do (making a delete survive a resync) now belongs to
    # IngestedMessage.dismissed_at, where it can't leave ghost rows in the
    # user's own orders list. See IngestedMessage for the full reasoning.

    # Full backup of the original source payload, same purpose as
    # discord-checkout-tracker's raw_json: nothing is ever silently dropped.
    # Duplicated onto IngestedMessage, which is the copy a rebuild reads --
    # this one travels with the order so an exported/edited order is still
    # self-describing.
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

    # Only meaningful when order_id is NULL -- a unit linked to an order
    # already has a product name via order.raw_product_text, so this stays
    # empty for those rather than duplicating it. Exists specifically for
    # spreadsheet-imported "stock I already hold" rows (see
    # docs/DATA-MODEL.md's Spreadsheet import section): without an order,
    # there was nowhere at all to record what the physical unit actually
    # IS, which made that import mode useless -- found while building it.
    product_text: Mapped[str | None] = mapped_column(default=None)

    # Set for standalone units (order_id NULL). A unit that HAS an order
    # inherits that order's product_id instead of duplicating it, so there
    # is exactly one place to fix if a product is ever re-identified.
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), default=None)

    # 'in_hand' | 'listed' | 'sold' | 'returned' | 'lost'
    status: Mapped[str] = mapped_column(default="in_hand")

    cost_basis: Mapped[float | None] = mapped_column(default=None)
    listed_price: Mapped[float | None] = mapped_column(default=None)
    listed_platform: Mapped[str | None] = mapped_column(default=None)
    sold_price: Mapped[float | None] = mapped_column(default=None)
    sold_at: Mapped[datetime | None] = mapped_column(default=None)
    sold_platform: Mapped[str | None] = mapped_column(default=None)

    # Selling and actually GETTING PAID are different events, often weeks
    # apart on consignment/marketplace payouts -- the user's own ledger has
    # tracked them as separate columns for years. status='sold' with this
    # still NULL is the state that matters: sold, money not in hand yet.
    # A timestamp rather than a boolean so "how long am I waiting?" is
    # answerable; the boolean is just `money_received_at is not None`.
    money_received_at: Mapped[datetime | None] = mapped_column(default=None)

    notes: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    # Kept ONLY for standalone units -- ones imported directly from a
    # spreadsheet in inventory mode, with no order behind them (order_id
    # NULL). Nothing re-syncs those, so a delete can't be undone by
    # re-materializing from a source the way an order's units can; the soft
    # delete is their sole safety net. Units that DO belong to an order are
    # hard deleted with it, because a rebuild recreates them.
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)

    user: Mapped["User"] = relationship(back_populates="inventory_items")
    order: Mapped["Order | None"] = relationship(back_populates="inventory_items")


class IngestedMessage(Base):
    """
    The record that a source (a Discord message, an imported spreadsheet
    row, a manual entry) was ever seen -- kept forever, separate from the
    Order it produces.

    WHY THIS EXISTS: an Order used to do three jobs at once -- it was the
    ingestion record, the business object you edit, AND the sync dedup key.
    Deleting one collapsed all three, so "I don't want to track this" was
    indistinguishable from "this never happened", and the only way to stop
    a resync recreating it was to keep a hidden tombstone Order around
    forever. That left ghost rows in a table the user thinks of as theirs.

    Splitting them means:
      - Orders can be HARD deleted. What you see is what exists.
      - Dedup is a property of ingestion, where it belongs: a message we've
        already seen is skipped whether or not an Order still exists for it.
      - `dismissed_at` says "seen, deliberately not tracked" -- that's what
        deleting an order sets, and it's what stops a resync bringing it back.
      - REBUILD is a local operation: the payload is kept, so orders can be
        re-materialized without re-reading Discord at all.

    `payload` is the COMPLETE inbound OrderCreate -- every field the source
    sent, including derived ones like `status`. Storing only the parser's
    raw field map was tried first and was wrong: `status` is computed by the
    bot's classify_checkout() and never appears in that map, so a rebuild
    silently defaulted 290 failed/cancelled orders to "success" -- and
    because success spawns inventory, invented hundreds of units that were
    never bought. The payload has to be the whole thing a rebuild needs, not
    the part that happens to look raw.

    It still isn't a byte-exact replay of the Discord embed (no colour or
    title), but it holds everything an Order is built from.
    """
    __tablename__ = "ingested_messages"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_ingested_source_external"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str]

    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    # When the source reported it (Discord's message timestamp), so a
    # rebuild can restore purchased_at without re-reading the channel.
    occurred_at: Mapped[datetime | None] = mapped_column(default=None)
    first_seen_at: Mapped[datetime] = mapped_column(default=_now)

    # Set when the user deletes the resulting order. The order row is really
    # gone; this is what makes that stick across a resync -- and clearing it
    # is what "rebuild" does.
    dismissed_at: Mapped[datetime | None] = mapped_column(default=None)


class Product(Base):
    """
    The canonical identity of a thing you buy and sell -- what makes "I hold
    12 of these" answerable at all.

    This exists because the SAME physical product arrives under wildly
    different names depending on where it came from. Measured across real
    data: a spreadsheet said "Pokémon TCG: Pitch Black PKC ETB" while the
    Discord bot said "1x Pokémon TCG: Mega Evolution-Pitch Black Pokémon
    Center Elite Trainer Box - 59.99 USD (OS)". Normalizing strings alone
    matched ZERO of 28 spreadsheet names against 52 Discord names, so
    string cleanup can never be the whole answer -- hence a real identity
    row that many raw names point AT, via ProductAlias.

    `normalized_key` is the deterministic fingerprint (see products.py's
    normalize()); it's what a never-before-seen raw name is first looked up
    by, before falling back to creating a new product.
    """
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_key", name="uq_products_user_key"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    # What the UI displays. Starts as the first raw name seen, and is
    # editable -- the user renaming a product must not change its identity,
    # which is why this is separate from normalized_key.
    canonical_name: Mapped[str]
    normalized_key: Mapped[str]

    category: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    aliases: Mapped[list["ProductAlias"]] = relationship(back_populates="product")


class ProductAlias(Base):
    """
    One raw product string -> one Product. Every distinct name any source
    has ever used gets a row here, so the mapping is a stored FACT rather
    than something re-derived (and re-guessed) on every read.

    Aliases are learned three ways, in descending confidence:
      1. exact normalized-key match (automatic, deterministic)
      2. two sources sharing an ORDER NUMBER but disagreeing on the product
         name -- a confirmed pairing, since the same order is the same
         purchase. This is how the hard cases get solved: 21 real alias
         pairs were recovered from the user's own data this way, including
         ones no normalizer could reach.
      3. the user merging two products by hand
    `source` records which, so a bad automatic guess can be found later.
    """
    __tablename__ = "product_aliases"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_key", name="uq_alias_user_key"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))

    raw_text: Mapped[str]
    normalized_key: Mapped[str]
    # 'exact' | 'order_number' | 'manual'
    source: Mapped[str] = mapped_column(default="exact")
    created_at: Mapped[datetime] = mapped_column(default=_now)

    product: Mapped["Product"] = relationship(back_populates="aliases")


class AppSetting(Base):
    """
    A flexible key-value store for things that aren't order/inventory data:
    dashboard chart preferences, the backup schedule, local license state.
    JSON `value` means each setting holds whatever shape it needs -- a
    boolean, a small object, a list -- without a schema change per setting.

    Deliberately not a dedicated table per concern (e.g. no `licenses`
    table): none of this is relational data, there's one row per (user,
    key), and the license state today is just a hardcoded test key with no
    real structure yet (see the memory note on swapping it before launch).
    """
    __tablename__ = "app_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_app_settings_user_key"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    # e.g. 'dashboard_prefs', 'backup_schedule', 'license'
    key: Mapped[str]
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=_now)

    user: Mapped["User"] = relationship(back_populates="app_settings")
