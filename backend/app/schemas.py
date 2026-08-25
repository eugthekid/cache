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
    # 'not_shipped' | 'label_created' | 'in_transit' | 'delivered' | 'exception'
    shipping_status: str = "not_shipped"
    tracking_number: Optional[str] = None
    ship_to_label: Optional[str] = None
    ship_to_address: Optional[str] = None
    purchased_at: Optional[datetime] = None
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
    ship_to_label: Optional[str]
    ship_to_address: Optional[str]
    purchased_at: Optional[datetime]
    created_at: datetime


class InventoryItemUpdate(BaseModel):
    """
    Covers the whole lifecycle a unit moves through: in_hand -> listed ->
    sold (or returned/lost at any point). `sold_at` is optional on purpose
    -- if a client marks something sold without sending a timestamp,
    crud.update_inventory_item fills in "now" rather than leaving it null.
    """

    status: Optional[str] = None  # 'in_hand' | 'listed' | 'sold' | 'returned' | 'lost'
    product_text: Optional[str] = None
    cost_basis: Optional[float] = None
    listed_price: Optional[float] = None
    listed_platform: Optional[str] = None
    sold_price: Optional[float] = None
    sold_at: Optional[datetime] = None
    sold_platform: Optional[str] = None
    # The UI sends a checkbox; crud.update_inventory_item translates it into
    # the stored money_received_at timestamp (or clears it). Callers that
    # know the real payout date can send money_received_at directly instead.
    money_received: Optional[bool] = None
    money_received_at: Optional[datetime] = None
    notes: Optional[str] = None


class InventoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: Optional[str]
    unit_index: Optional[int]
    status: str
    product_text: Optional[str]
    product_id: Optional[str]
    cost_basis: Optional[float]
    listed_price: Optional[float]
    listed_platform: Optional[str]
    sold_price: Optional[float]
    sold_at: Optional[datetime]
    sold_platform: Optional[str]
    money_received_at: Optional[datetime]
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
    status: str  # 'in_hand' | 'listed' | 'sold' | 'returned' | 'lost'


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
    in_hand: int
    listed: int
    sold: int
    total_cost_basis: float
    total_sold_revenue: float
    awaiting_payment: int
    # Catalog image if matched, else the most recent order's embed
    # thumbnail, else null -- see routers/products.py's resolution order.
    image_url: Optional[str] = None


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


class LicenseActivate(BaseModel):
    key: str


class LicenseStatus(BaseModel):
    activated: bool
    # Last 4 characters only -- enough for a user to recognize their own
    # key on the Settings screen, never enough to reconstruct it.
    key_suffix: Optional[str] = None
    activated_at: Optional[datetime] = None
