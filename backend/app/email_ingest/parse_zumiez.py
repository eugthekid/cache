"""
parse_zumiez.py
---------------
Zumiez order emails -> order lines. Built 2026-10-26 against the user's two
real orders (#35000118411 and #35000119158, both a Santa Cruz x Pokémon TCG
Blind Bag Skateboard Deck) -- every email shape below was read from a live
IMAP fetch through imap_client.fetch_plaintext_body(), i.e. exactly what the
poller sees, not from the Gmail web view.

The four templates seen (subjects are matched in classify.py):

  CONFIRMATION  "We have received your order #35000118411"   (help@zumiez.com)
      HTML-only -- no text/plain part -- so the body is html_to_text()'s
      pipe-table rendering. Every item row appears THREE times (the
      template carries desktop/mobile copies of the same table), and only
      the last copy is followed by "| qty | $price |". So items are read
      from rows that end in a quantity and price, and de-duplicated by SKU
      and size.
      Prices are pre-tax; the email shows Subtotal, Tax and Grand Total, so
      each unit's cost is its price scaled by Grand Total / Subtotal -- the
      same "what you actually paid" basis the Target and Pokémon Center
      parsers use.

  SHIPPED       "We've shipped a package to you!"             (noreply@zumiez.com)
      Order number and the items in this package (name, qty, SKU, price),
      but NO tracking number. The subject is generic, so the body must
      carry a Zumiez order number or nothing is claimed.

  OUT FOR DELIVERY / DELIVERED
                "A package for order #N is out for delivery" / "... has been delivered"
      Order number and tracking number only -- the item block is present
      but empty ("Item #:", "Size:", "Quantity:" with no values).

  CANCELLED     "OH NO! YOUR RECENT ZUMIEZ ORDER HAS BEEN CANCELLED"
      The one real example carried NO order number (the user says it was a
      one-off error email), so it is deliberately not parsed. Build it from
      a real cancellation that names its order when one arrives.

SKUs: the confirmation writes "us41298006980102", the shipping email
"41298006980102". Both are reduced to the digits so the two match.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# Every Zumiez email carries the company's Lynnwood, WA address in its
# footer; the generic "We've shipped a package to you!" subject needs this
# check so another store's identical subject can't be read as Zumiez.
_SIGNATURE = re.compile(r"zumiez|4001 204th Street S(?:outh)?w(?:est)?", re.I)

_ORDER_NUMBER = re.compile(r"Order\s*#\s*:?\s*(\d{8,})", re.I)
_MONEY = r"\$([\d,]+\.\d{2})"

# One confirmation item row: "| <name> SKU: us123... Size 8.0 | 1 | $139.95 |"
_CONFIRM_ITEM = re.compile(
    r"\|\s*([^|]+?)\s+SKU:\s*([A-Za-z]*)(\d+)(?:\s+Size\s+([^\s|]+))?\s*\|\s*(\d+)\s*\|\s*" + _MONEY,
    re.S,
)
_SUBTOTAL = re.compile(r"Subtotal\s*\|\s*" + _MONEY, re.I)
_GRAND_TOTAL = re.compile(r"Grand Total\s*\|\s*" + _MONEY, re.I)
_PLACED_ON = re.compile(r"Placed on (\w{3} \d{1,2}, \d{4}), (\d{1,2}:\d{2}:\d{2} [AP]M)")
_SHIP_TO = re.compile(r"Shipping Info\s+(.+?)\s+United States", re.S)

# Shipping email item block:
#   *Santa Cruz x Pokémon TCG Blind Bag Skateboard Deck*
#   Qty: 1 | SKU: 41298006980102
#   Price: $139.95
_SHIPPED_ITEM = re.compile(
    r"\*([^*\n]+)\*\s*\n\s*Qty:\s*(\d+)\s*\|\s*SKU:\s*[A-Za-z]*(\d+)\s*\n\s*Price:\s*" + _MONEY
)
_TRACKING = re.compile(r"Tracking\s*#\s*:?\s*([A-Z0-9]{8,})", re.I)
_ETA = re.compile(r"ETA:\s*([A-Za-z]+,\s*[A-Za-z]+ \d{1,2})")


@dataclass
class Line:
    raw_product_text: str
    quantity: int
    unit_price: Optional[float]  # tax-inclusive on confirmations; None when the email has no price
    external_sku: str


def _money(value: str) -> float:
    return float(value.replace(",", ""))


def _name(name: str, size: Optional[str]) -> str:
    """The product name, with a size written as a dashed variant
    ("... Skateboard Deck - Size 8.0") so different sizes stay separate
    products and group as variants of one item."""
    name = re.sub(r"\s+", " ", name).strip()
    return f"{name} - Size {size}" if size else name


def is_zumiez(body: str) -> bool:
    return bool(_SIGNATURE.search(body or ""))


def parse_order_number(body: str) -> Optional[str]:
    m = _ORDER_NUMBER.search(body or "")
    return m.group(1) if m else None


def parse_purchased_at(body: str) -> Optional[str]:
    """ISO timestamp from "Placed on Oct 17, 2026, 5:02:43 PM". The email
    doesn't say which time zone (Zumiez is in Washington state), so it is
    kept as written."""
    m = _PLACED_ON.search(body or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%b %d, %Y %I:%M:%S %p").isoformat()
    except ValueError:
        return None


def parse_ship_to_address(body: str) -> Optional[str]:
    m = _SHIP_TO.search(body or "")
    if not m:
        return None
    parts = [re.sub(r"\s+", " ", p).strip(" ,") for p in m.group(1).splitlines()]
    return ", ".join(p for p in parts if p)


def parse_confirmation(body: str) -> list[Line]:
    body = body or ""
    seen: dict[tuple[str, Optional[str]], Line] = {}
    for m in _CONFIRM_ITEM.finditer(body):
        name, _prefix, sku, size, qty, price = m.groups()
        # The name group can swallow the tail of a previous duplicate cell
        # ("8.0 | Santa Cruz ..."); keep only the text after the last "|".
        name = name.split("|")[-1]
        key = (sku, size)
        if key not in seen:
            seen[key] = Line(_name(name, size), int(qty), _money(price), sku)
    lines = list(seen.values())

    subtotal = _SUBTOTAL.search(body)
    total = _GRAND_TOTAL.search(body)
    if lines and subtotal and total and _money(subtotal.group(1)) > 0:
        factor = _money(total.group(1)) / _money(subtotal.group(1))
        for line in lines:
            line.unit_price = round(line.unit_price * factor, 2)
    return lines


def parse_shipped_lines(body: str) -> list[Line]:
    return [
        Line(re.sub(r"\s+", " ", name).strip(), int(qty), _money(price), sku)
        for name, qty, sku, price in _SHIPPED_ITEM.findall(body or "")
    ]


def parse_tracking_number(body: str) -> Optional[str]:
    m = _TRACKING.search(body or "")
    return m.group(1) if m else None


def parse_eta(body: str) -> Optional[str]:
    """ "Friday, October 23" -- no year in the email."""
    m = _ETA.search(body or "")
    return re.sub(r"\s+", " ", m.group(1)) if m else None
