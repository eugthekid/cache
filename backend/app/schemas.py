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
    profile: Optional[str]
    site: Optional[str]
    module: Optional[str]
    category: Optional[str]
    quantity: Optional[int]
    unit_price: Optional[float]
    currency: str
    order_number: Optional[str]
    order_url: Optional[str]
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
    notes: Optional[str] = None


class InventoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: Optional[str]
    unit_index: Optional[int]
    status: str
    product_text: Optional[str]
    cost_basis: Optional[float]
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


class LicenseActivate(BaseModel):
    key: str


class LicenseStatus(BaseModel):
    activated: bool
    # Last 4 characters only -- enough for a user to recognize their own
    # key on the Settings screen, never enough to reconstruct it.
    key_suffix: Optional[str] = None
    activated_at: Optional[datetime] = None
