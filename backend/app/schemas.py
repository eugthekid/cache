"""
schemas.py
----------
Pydantic models define the API's request/response shapes -- separate from
models.py (the database shapes). Keeping them separate means the API contract
can stay stable even as the database evolves (e.g. adding product_id later
doesn't have to change what a client already expects to receive).
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    name: str
    config: dict[str, Any]
    last_synced_at: Optional[datetime]
    created_at: datetime


class OrderCreate(BaseModel):
    """What a client sends to record a new checkout attempt."""

    source_id: str
    external_id: str
    status: str  # 'success' | 'failed' | 'cancelled' | 'pending'
    failure_reason: Optional[str] = None
    raw_product_text: Optional[str] = None
    profile: Optional[str] = None
    site: Optional[str] = None
    module: Optional[str] = None
    category: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    currency: str = "USD"
    order_number: Optional[str] = None
    order_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    # The retailer's own per-line identifier -- Pokemon Center's "SKU #:
    # 10-10449-122", present on every line of every confirmation, shipping
    # and cancellation email. Declared here so matching.match_line()'s SKU
    # rule (its strongest) actually has something to receive: this field
    # existed on the Order model and in claims.CLAIMED_FIELDS already, but
    # was never on OrderCreate, so crud.find_existing_line's
    # `getattr(order_in, "external_sku", None)` was silently always None --
    # found while wiring the email connector, which is what would have
    # exercised it first.
    external_sku: Optional[str] = None
    # 'not_shipped' | 'label_created' | 'in_transit' | 'delivered' | 'exception'
    shipping_status: str = "not_shipped"
    tracking_number: Optional[str] = None
    # The carrier/retailer's own latest scan description, verbatim (e.g.
    # "Delivered June 1, 2026") -- same missing-field gap external_sku
    # had before it: declared in claims.CLAIMED_FIELDS and on the Order
    # model already, but never reachable from an inbound claim until a
    # real caller (Target's ARRIVED claim) needed it.
    tracking_detail: Optional[str] = None
    ship_to_label: Optional[str] = None
    ship_to_address: Optional[str] = None
    purchased_at: Optional[datetime] = None
    # When the SOURCE emitted this message, which is not always when the
    # purchase happened. For a Discord webhook the two coincide. For email
    # they can be months apart: a cancellation sent 7 September about an
    # order placed 15 July carries purchased_at=July 15, and using that as
    # the message time would leave it tied with the confirmation instead
    # of superseding it -- so claim resolution would pick between them
    # arbitrarily (see app/claims.py, "recency breaks ties"). Sources that
    # have a real message timestamp (an email's Date header) must send it
    # here; omitting it falls back to purchased_at, preserving the
    # existing behaviour for every Discord source.
    occurred_at: Optional[datetime] = None
    raw_json: dict[str, Any] = {}


class OrderUpdate(BaseModel):
    """
    A partial update -- only fields that are actually editable after an
    order's been created. `exclude_unset=True` on the receiving end means a
    client only sends the fields it's actually changing; omitted fields are
    left alone rather than getting overwritten with None.
    """

    status: Optional[str] = None
    failure_reason: Optional[str] = None
    raw_product_text: Optional[str] = None
    profile: Optional[str] = None
    site: Optional[str] = None
    category: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    order_number: Optional[str] = None
    order_url: Optional[str] = None
    shipping_status: Optional[str] = None
    tracking_number: Optional[str] = None
    ship_to_label: Optional[str] = None
    ship_to_address: Optional[str] = None
    purchased_at: Optional[datetime] = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    external_id: str
    status: str
    failure_reason: Optional[str]
    raw_product_text: Optional[str]
    product_id: Optional[str]
    # The matched product's standardized name, falling back to
    # raw_product_text -- see Order.product_name.
    product_name: Optional[str]
    profile: Optional[str]
    site: Optional[str]
    retailer: Optional[str]
    module: Optional[str]
    category: Optional[str]
    quantity: Optional[int]
    unit_price: Optional[float]
    currency: str
    order_number: Optional[str]
    order_url: Optional[str]
    thumbnail_url: Optional[str]
    shipping_status: str
    tracking_number: Optional[str]
    carrier: Optional[str]
    # Human label ("UPS") and a deep link to the carrier's own page --
    # both computed from carrier/tracking_number, see Order.carrier_label
    # and Order.tracking_url.
    carrier_label: Optional[str]
    tracking_url: Optional[str]
    estimated_delivery: Optional[str]
    tracking_detail: Optional[str]
    tracking_checked_at: Optional[datetime]
    shipping_alert_at: Optional[datetime]
    shipping_alert_seen_at: Optional[datetime]
    ship_to_label: Optional[str]
    ship_to_address: Optional[str]
    purchased_at: Optional[datetime]
    created_at: datetime


class InventoryItemCreate(BaseModel):
    """
    Manually add stock you already hold, one line at a time -- the
    lightweight alternative to running the whole spreadsheet importer for
    a single item. Produces the same shape as import's mode='unit' rows
    (order_id=None, a free-text product_text instead of a linked Product).
    """

    product_text: str
    quantity: int = 1
    status: str = "in_hand"  # 'not_shipped' | 'in_transit' | 'in_hand' | 'sold' | 'returned' | 'lost'
    cost_basis: Optional[float] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class InventoryItemUpdate(BaseModel):
    """
    Covers the whole lifecycle a unit moves through: not_shipped ->
    in_transit -> in_hand -> sold (or returned/lost at any point; the
    first three are normally automatic, see crud.reconcile_order_inventory,
    but stay editable here for a manual correction). `sold_at` is optional
    on purpose -- if a client marks something sold without sending a
    timestamp, crud.update_inventory_item fills in "now" rather than
    leaving it null.
    """

    status: Optional[str] = None  # 'not_shipped' | 'in_transit' | 'in_hand' | 'sold' | 'returned' | 'lost'
    product_text: Optional[str] = None
    cost_basis: Optional[float] = None
    location: Optional[str] = None
    listed_price: Optional[float] = None
    listed_platform: Optional[str] = None
    sold_price: Optional[float] = None
    sold_at: Optional[datetime] = None
    sold_platform: Optional[str] = None
    notes: Optional[str] = None


class InventoryBulkUpdate(InventoryItemUpdate):
    """
    Same partial-update shape as InventoryItemUpdate, applied to a whole
    selection at once -- "adjust price/location/platform/etc. across
    these N units" rather than "change one thing on all of them." Only
    the fields actually set get changed, same as the single-item PATCH
    (see crud.update_inventory_item's exclude_unset handling); a field
    left out of the request is untouched on every unit, not blanked.
    """

    ids: list[str]


class InventoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: Optional[str]
    unit_index: Optional[int]
    status: str
    product_text: Optional[str]
    product_id: Optional[str]
    cost_basis: Optional[float]
    location: Optional[str]
    listed_price: Optional[float]
    listed_platform: Optional[str]
    sold_price: Optional[float]
    sold_at: Optional[datetime]
    sold_platform: Optional[str]
    notes: Optional[str]
    created_at: datetime


class SettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: dict[str, Any]
    updated_at: datetime


class SettingUpdate(BaseModel):
    """The whole value is replaced, not merged -- callers own the full
    shape of their setting (e.g. the complete dashboard-prefs object)."""

    value: dict[str, Any]


class BulkIds(BaseModel):
    """Shared shape for every bulk action -- the set of rows a checkbox
    selection in the UI resolved to."""

    ids: list[str]


class BulkOrderStatusUpdate(BaseModel):
    ids: list[str]
    status: str  # 'success' | 'failed' | 'cancelled' | 'pending'


class BulkInventoryStatusUpdate(BaseModel):
    ids: list[str]
    status: str  # 'not_shipped' | 'in_transit' | 'in_hand' | 'sold' | 'returned' | 'lost'


class BulkResult(BaseModel):
    updated: int


class RebuildRequest(BaseModel):
    # None = every source. Set it to rebuild just one channel's deletions.
    source_id: Optional[str] = None


class RebuildResult(BaseModel):
    rebuilt: int
    skipped: int


class DeletedSummary(BaseModel):
    """How much is recoverable, so the UI can offer Rebuild honestly
    instead of showing a button that might do nothing."""
    dismissed: int
    rebuildable: int


class ProductOut(BaseModel):
    id: str
    canonical_name: str
    normalized_key: str
    category: Optional[str] = None
    alias_count: int = 0


class ProductGroup(BaseModel):
    """One row of the grouped inventory view."""
    product_id: Optional[str]
    name: Optional[str]
    total_units: int
    # Pre-delivery pipeline, in order: not_shipped -> in_transit -> in_hand.
    # See crud.item_status_for_shipping for how a unit moves between these
    # automatically as its order's shipping_status updates from email or
    # live tracking -- 'listed' is gone (nothing sets it anymore).
    not_shipped: int
    in_transit: int
    in_hand: int
    sold: int
    total_cost_basis: float
    # total_cost_basis / units actually carrying a recorded cost -- NOT
    # total_cost_basis / total_units, which would understate the average
    # by diluting it with units nobody ever priced (imports, manual adds
    # with no purchase price). None when nothing here has a price at all.
    avg_cost_basis: Optional[float] = None
    total_sold_revenue: float
    # None when nothing's sold yet -- distinct from 0, which would claim
    # units sold for free.
    avg_sale_price: Optional[float] = None
    # sum(sold_price - cost_basis) over sold, priced units only -- NOT
    # total_sold_revenue minus total_cost_basis, which would wrongly charge
    # this product for units still sitting in hand or listed. None under
    # the same rule as avg_sale_price: nothing sold yet is not the same
    # claim as "sold at a $0 profit".
    total_profit: Optional[float] = None
    # Catalog image if matched, else the most recent order's embed
    # thumbnail, else null -- see routers/products.py's resolution order.
    image_url: Optional[str] = None
    category: Optional[str] = None


class ProductMerge(BaseModel):
    source_id: str
    target_id: str


class ProductRename(BaseModel):
    canonical_name: str
    category: Optional[str] = None


class MergeSuggestion(BaseModel):
    source_id: str
    target_id: str
    source_name: str
    target_name: str
    reason: str


class ProductRebuildResult(BaseModel):
    orders_resolved: int
    items_resolved: int
    products: int
    suggestions: int


class CatalogSyncRequest(BaseModel):
    category: str  # 'pokemon' | 'onepiece'


class CatalogSyncResult(BaseModel):
    sets: int
    sets_failed: int
    products_upserted: int


class CatalogMatchResult(BaseModel):
    duplicates_merged: int
    auto_confirmed: int
    suggested: int
    unmatched: int


class CatalogSuggestion(BaseModel):
    product_id: str
    our_name: str
    candidate_id: str
    candidate_name: str
    candidate_image_url: Optional[str] = None
    candidate_set: Optional[str] = None


class CatalogCandidate(BaseModel):
    id: str
    name: str
    image_url: Optional[str] = None
    set_name: Optional[str] = None
    score: float


class CatalogConfirm(BaseModel):
    catalog_product_id: str


class SyncSourceStatus(BaseModel):
    id: str
    name: str
    last_synced_at: Optional[datetime]


class SyncStatus(BaseModel):
    pending: bool
    requested_at: Optional[str] = None
    full: bool = False
    sources: list[SyncSourceStatus] = []


class SyncRequest(BaseModel):
    # True = re-walk entire channel history (recovers a wiped database);
    # False = only messages newer than each source's last_synced_at.
    full: bool = True


class SyncClaim(BaseModel):
    claimed: bool
    full: bool


class SourceSynced(BaseModel):
    last_synced_at: Optional[datetime] = None


class BotServiceStatus(BaseModel):
    supported: bool
    installed: bool
    running: bool
    log_path: Optional[str] = None


class DiscordConfigIn(BaseModel):
    """What the Settings 'Connect Discord' form submits. `token` is
    optional on resubmit -- leaving it blank keeps whatever token is
    already written to bot/.env, so changing just the channel scope
    doesn't force re-pasting the token every time."""

    token: Optional[str] = None
    guild_id: str
    channel_scope: str  # 'all' | 'specific'
    channel_ids: Optional[str] = None  # comma-separated; only used when channel_scope == 'specific'
    profile_filter: Optional[str] = None  # comma-separated


class DiscordStatus(BaseModel):
    configured: bool
    # Last 4 characters only -- same convention as LicenseStatus.key_suffix.
    token_suffix: Optional[str] = None
    guild_id: Optional[str] = None
    channel_scope: Optional[str] = None
    channel_ids: Optional[str] = None
    profile_filter: Optional[str] = None


class EmailConfigIn(BaseModel):
    """What the Settings 'Connect Email' form submits. `app_password` is
    optional on resubmit -- same reasoning as DiscordConfigIn.token:
    leaving it blank keeps whatever is already written to email.env, so
    fixing a typo'd address doesn't force re-pasting the password too."""

    address: str
    app_password: Optional[str] = None


class EmailStatus(BaseModel):
    configured: bool
    address: Optional[str] = None
    # Last 4 characters only -- same convention as DiscordStatus.token_suffix
    # and LicenseStatus.key_suffix: enough to recognize your own without
    # ever re-displaying the secret itself.
    app_password_suffix: Optional[str] = None
    # Whether app/email_poller.py's background thread is actually alive
    # right now. No install/uninstall/running-vs-crashed distinction to
    # show here the way Discord's LaunchAgent status needs -- it's an
    # in-process thread the backend itself owns, so "configured" and
    # "running" converge to the same thing except for the brief window
    # right after a save.
    polling: bool = False


class TrackingConfigIn(BaseModel):
    """What Settings' 'Connect tracking' form submits. Just the one
    credential -- 17TRACK needs no username/address the way email does."""

    api_key: str


class TrackingStatus(BaseModel):
    configured: bool
    provider: Optional[str] = None
    # Last 4 characters only -- same convention as EmailStatus.app_password_suffix.
    api_key_suffix: Optional[str] = None
    # Whether app/tracking_poller.py's background thread is alive right
    # now -- same in-process-thread shape as email_poller.py, not a
    # separate installed service.
    polling: bool = False


class LicenseActivate(BaseModel):
    key: str


class LicenseStatus(BaseModel):
    activated: bool
    # Last 4 characters only -- enough for a user to recognize their own
    # key on the Settings screen, never enough to reconstruct it.
    key_suffix: Optional[str] = None
    activated_at: Optional[datetime] = None
