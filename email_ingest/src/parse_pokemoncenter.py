"""
parse_pokemoncenter.py
-----------------------
Turns a Pokémon Center confirmation email body into one claim dict per cart
line -- the shape app/claims.py's build_claim() already expects (see
backend/app/claims.py and backend/app/schemas.py's OrderCreate).

STRUCTURE, verified against real mail (order P0038875758, thread
19f675e3a4060d74): the body is a sequence of "| |"-delimited table rows (a
plaintext rendering of an HTML email table). Each cart line is three
consecutive rows:

    Pokémon TCG: 30th Celebration Tech Sticker Collection (Lucario)
    SKU #: 10-10449-122 Qty: 1 Price: $14.99

followed by a blank "| |" separator row before the next line or before
"Order Subtotal". The block is bounded above by "Order Summary" and below
by "Order Subtotal" -- text outside that window (shipping address,
"Recently viewed"-style upsells if PC ever adds them) is deliberately never
scanned, which is what keeps this immune to the upsell-block trap confirmed
on Target and Walmart (see docs/RECONNAISSANCE.md).

TAX ALLOCATION: PC's confirmation gives one cart-level Sales Tax figure,
not a per-line one. Proportional allocation by extended line price
(unit_price * qty) is the same discriminator already verified against
real data; that's what unit_price below returns -- the tax-inclusive
per-unit cost, not the raw catalog price -- because that IS the number
Cache's cost_basis field means to hold.

DELIBERATELY NOT ROUNDED TO THE CENT PER LINE. First draft rounded each
line's unit_price to 2 decimals before returning it, which reconciles
per-line but NOT in aggregate: verified against order P0038875758 (Qty 2
line, $119.98 extended + $10.65 allocated tax = $130.635, which only
divides evenly into 2 units by rounding one to $65.32 and the other to
$65.31 -- rounding both the same way instead drifts the order total by a
cent, $163.28 vs the stated $163.27). `InventoryItem.cost_basis` is a
plain float column (see backend/app/models.py), not a fixed-point cents
type, so there is no real constraint forcing 2-decimal precision here --
returning the unrounded per-unit share lets the sum reconcile to the
stated Order Total exactly, which matters more than a tidy-looking number
on one unit.
"""

import re
from dataclasses import dataclass
from typing import Optional

# One row: "| SKU #: 10-10449-122 Qty: 1 Price: $14.99 |". Every field on
# one line, which is what makes this safe to anchor a whole-string search
# on -- no cross-line bridging needed for this row.
_SKU_ROW_RE = re.compile(
    r"SKU\s*\#\s*:\s*(?P<sku>[\w-]+).*?Qty\s*:\s*(?P<qty>\d+).*?Price\s*:\s*\$(?P<price>[\d,]+\.\d{2})"
)
# A plain "| name |" row -- deliberately excludes rows containing "SKU"
# (the field row itself) so the two never get confused for each other.
_NAME_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*$")

_ORDER_NUMBER_RE = re.compile(r"Order Number:\s*([A-Z0-9]+)")
_ORDER_DATE_RE = re.compile(r"Date Ordered:\s*([A-Za-z]+ \d{1,2}, \d{4})")
_SUBTOTAL_RE = re.compile(r"Order Subtotal\s*\|\s*\$([\d,]+\.\d{2})")
_TAX_RE = re.compile(r"Sales Tax\s*\|\s*\$([\d,]+\.\d{2})")
_SHIP_RE = re.compile(r"Shipping\s*\|\s*\$([\d,]+\.\d{2})")


@dataclass
class Line:
    raw_product_text: str
    external_sku: str
    quantity: int
    unit_price: float  # tax-and-shipping-inclusive, see module docstring


def _to_float(money: str) -> float:
    return float(money.replace(",", ""))


def parse_confirmation(body: str) -> list[Line]:
    """
    Extract every cart line between "Order Summary" and "Order Subtotal",
    with tax and shipping allocated proportionally across lines by their
    extended (pre-tax) price.

    Returns [] rather than raising when the expected section markers
    aren't found -- a template change should surface as "0 lines parsed,
    go look at it", never as an ingestion crash.
    """
    summary_start = body.find("Order Summary")
    subtotal_match = _SUBTOTAL_RE.search(body)
    if summary_start == -1 or not subtotal_match:
        return []
    window = body[summary_start:subtotal_match.start()]

    # Walk the window LINE BY LINE rather than one bridging regex: a SKU
    # row is matched to the plain-text row immediately preceding it. A
    # combined "name ... SKU" pattern with an unconstrained gap between
    # them was tried first and picked up a blank "| |" separator row as
    # the "name" instead of skipping to the real one several lines later
    # -- confirmed live against this exact fixture, silently pairing every
    # line's SKU with an empty name. Adjacency, not a regex bridge, is
    # what actually guarantees the right name attaches to the right SKU.
    raw_lines: list[tuple[str, str, int, float]] = []
    pending_name: Optional[str] = None
    for line in window.splitlines():
        sku_m = _SKU_ROW_RE.search(line)
        if sku_m:
            if pending_name:
                raw_lines.append(
                    (pending_name, sku_m.group("sku"), int(sku_m.group("qty")), _to_float(sku_m.group("price")))
                )
            pending_name = None
            continue
        name_m = _NAME_ROW_RE.match(line)
        if name_m:
            text = name_m.group(1).strip()
            pending_name = text if text else None
        # Any other line (blank row with no pipes, "Order Summary" itself
        # once trimmed to just that word, etc.) neither sets nor clears
        # pending_name -- a stray non-row line between a name and its SKU
        # row has never been observed, so this stays permissive rather
        # than brittle about exact spacing.

    if not raw_lines:
        return []

    tax_m = _TAX_RE.search(body)
    ship_m = _SHIP_RE.search(body)
    tax = _to_float(tax_m.group(1)) if tax_m else 0.0
    shipping = _to_float(ship_m.group(1)) if ship_m else 0.0
    extras = tax + shipping

    extended = [price * qty for _, _, qty, price in raw_lines]
    pretax_total = sum(extended)

    out: list[Line] = []
    for (name, sku, qty, price), ext in zip(raw_lines, extended):
        share = (ext / pretax_total * extras) if pretax_total else 0.0
        # Not rounded here -- see module docstring on why per-line rounding
        # would drift the order total by a cent on any qty > 1 line.
        unit_price = (ext + share) / qty
        out.append(Line(raw_product_text=name, external_sku=sku, quantity=qty, unit_price=unit_price))
    return out


def parse_order_number(body: str) -> Optional[str]:
    m = _ORDER_NUMBER_RE.search(body)
    return m.group(1) if m else None


def parse_purchased_at(body: str) -> Optional[str]:
    """Returns the raw 'Month DD, YYYY' string; caller parses to a date --
    kept a plain string here so this module stays free of a datetime
    dependency it doesn't otherwise need."""
    m = _ORDER_DATE_RE.search(body)
    return m.group(1) if m else None
