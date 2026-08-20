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
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    currency: str = "USD"
    order_number: Optional[str] = None
    order_url: Optional[str] = None
    purchased_at: Optional[datetime] = None
    raw_json: dict[str, Any] = {}


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
    quantity: Optional[int]
    unit_price: Optional[float]
    currency: str
    order_number: Optional[str]
    order_url: Optional[str]
    purchased_at: Optional[datetime]
    created_at: datetime


class InventoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: Optional[str]
    unit_index: Optional[int]
    status: str
    cost_basis: Optional[float]
    listed_price: Optional[float]
    listed_platform: Optional[str]
    sold_price: Optional[float]
    sold_at: Optional[datetime]
    sold_platform: Optional[str]
    notes: Optional[str]
    created_at: datetime
