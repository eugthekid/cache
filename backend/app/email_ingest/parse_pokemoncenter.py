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
# LEADING WHITESPACE TOLERATED (added after a live parse failure, see
# _extract_no_price_lines' docstring): PC's cancellation template renders
# through a more deeply nested HTML table than the confirmation fixture
# this module was originally verified against, so real name/SKU rows can
# carry indentation before the "|" rather than starting at column 0.
# (the field row itself) so the two never get confused for each other.
_NAME_ROW_RE = re.compile(r"^\s*\|\s*([^|]+?)\s*\|\s*$")

_ORDER_NUMBER_RE = re.compile(r"Order Number:\s*([A-Z0-9]+)")
_ORDER_DATE_RE = re.compile(r"Date Ordered:\s*([A-Za-z]+ \d{1,2}, \d{4})")
_SUBTOTAL_RE = re.compile(r"Order Subtotal\s*\|\s*\$([\d,]+\.\d{2})")
_TAX_RE = re.compile(r"Sales Tax\s*\|\s*\$([\d,]+\.\d{2})")
_SHIP_RE = re.compile(r"Shipping\s*\|\s*\$([\d,]+\.\d{2})")

# "Tracking Number: 876939896536[](https://click.em.pokemon.com/...)" --
# verified against real mail (order P0038927021, thread 1a0a5ce2cc85a81b):
# the number is immediately followed by a markdown-style link marker with
# NO separating space, so a plain \S+ capture would swallow the whole
# link. Alnum-only stops at the "[" on its own, no lookahead needed.
_TRACKING_RE = re.compile(r"Tracking Number:\s*([A-Za-z0-9]+)")

# Cancellation rows carry SKU and Qty but no Price -- verified against 2
# real cancellation emails (orders P0038894998 and P0038918210, threads
# 1a07c7bf674b6dee and 1a07c7bf20af1f52): same 3-row-per-line table shape
# as parse_confirmation's SKU row, just missing the trailing "Price: $x.xx"
# field entirely, not merely blank. A separate regex rather than making
# Price optional in _SKU_ROW_RE, so a confirmation row that's silently
# missing its price (a real parse failure) still fails loudly there.
_CANCEL_SKU_ROW_RE = re.compile(r"SKU\s*\#\s*:\s*(?P<sku>[\w-]+).*?Qty\s*:\s*(?P<qty>\d+)")

# Fallback pair for the SAME row when SKU and Qty land on two separate
# physical lines instead of one -- found live 2026-09-18 against a batch of
# 18 real cancellation emails (all from 2026-09-07), none of which
# _CANCEL_SKU_ROW_RE matched: PC's more-nested cancellation table wraps
# "SKU #: ..." and "Qty: N" onto consecutive lines rather than one. Each
# regex anchors the WHOLE line deliberately -- these emails also render the
# same row 2-3 more times at shallower nesting, and those extra copies come
# out mangled (a Qty and the NEXT item's SKU glued onto one line with no
# line break between them). A whole-line anchor only matches the first,
# clean copy and silently fails closed on the mangled ones, same "refuse to
# guess" discipline as parse_confirmation's subtotal cross-check above --
# a dropped duplicate is fine; a wrong pairing from a mangled row is not.
_SKU_ONLY_ROW_RE = re.compile(r"^\s*\|?\s*SKU\s*\#\s*:\s*(?P<sku>[\w-]+)\s*$")
_QTY_ONLY_ROW_RE = re.compile(r"^\s*Qty\s*:\s*(?P<qty>\d+)\s*\|?\s*$")


@dataclass
class Line:
    raw_product_text: str
    external_sku: str
    quantity: int
    unit_price: float  # tax-and-shipping-inclusive, see module docstring


@dataclass
class NoPriceLine:
    """Shared by parse_cancelled_lines and parse_shipped_lines -- PC's
    cancellation and shipping templates both list per-line SKU/Qty in the
    identical row shape (just an extra space around "#" in the shipping
    one, already tolerated by _CANCEL_SKU_ROW_RE), and NEITHER states a
    price for the line -- unlike the confirmation template's Line, which
    is the one place PC ever gives one. $0.00 would misrepresent
    'unknown' as 'free', so this carries none at all; callers match it
    back to the order's existing line by external_sku rather than
    re-deriving a cost from it."""

    raw_product_text: str
    external_sku: str
    quantity: int


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

    extended_pre_check = sum(qty * price for _, _, qty, price in raw_lines)
    stated_subtotal = _to_float(subtotal_match.group(1))
    # Cross-check against the stated Order Subtotal, found during review:
    # nothing previously verified that every line actually got captured --
    # a row whose SKU/Qty/Price didn't match _SKU_ROW_RE (a template
    # tweak, an unexpected 4th line) would silently drop out of raw_lines,
    # and tax/shipping would then be allocated across too few lines,
    # overstating every captured line's cost_basis rather than failing
    # visibly. A mismatch here means "something wasn't parsed", so this
    # returns [] rather than a wrong allocation.
    if abs(extended_pre_check - stated_subtotal) > 0.01:
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


# Verified live 2026-09-19 against real confirmation mail: the row reads
# "| ... US | Shipping Address:\n<multi-line address>\nUS |" -- the SAME
# "Shipping Address:" label PC used in an earlier single-line rendering
# (see parse_confirmation's own module docstring precedent for this
# template drifting between captures), now wrapped across several
# indented lines instead of one. Bounded to the next "|" either way, so
# both renderings are covered without needing two regexes.
_SHIP_TO_RE = re.compile(r"Shipping Address:\s*([^|]+?)\s*\|", re.IGNORECASE)


def parse_ship_to_address(body: str) -> Optional[str]:
    """The confirmation's own "Shipping Address:" block, whitespace
    (including the line-wrapping the real template uses) collapsed to a
    single readable line. Returns None when the marker isn't found --
    same discipline as every other parser here, never guessed."""
    m = _SHIP_TO_RE.search(body)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip() or None


def parse_purchased_at(body: str) -> Optional[str]:
    """Returns the raw 'Month DD, YYYY' string; caller parses to a date --
    kept a plain string here so this module stays free of a datetime
    dependency it doesn't otherwise need."""
    m = _ORDER_DATE_RE.search(body)
    return m.group(1) if m else None


def parse_tracking_number(body: str) -> Optional[str]:
    """For a SHIPPED email. Order number for these comes from
    parse_order_number -- PC's "Order Details" block ("Order Number:
    P0038927021") is unchanged from the confirmation template, verified
    against real mail (order P0038927021)."""
    m = _TRACKING_RE.search(body)
    return m.group(1) if m else None


def _extract_no_price_lines(body: str) -> list[NoPriceLine]:
    """
    Shared by parse_cancelled_lines and parse_shipped_lines -- see
    NoPriceLine's docstring for why the same extraction serves both.

    Bounded to "Order Summary" onward, same as parse_confirmation, but
    with NO closing marker -- neither template has an "Order Subtotal"
    line to bound against (there's nothing to sum; see NoPriceLine).
    Safe anyway: _CANCEL_SKU_ROW_RE requires a literal "SKU #:" that
    never appears in the nav/legal footer text following the real lines,
    so nothing there can be mistaken for one.

    Returns [] when "Order Summary" isn't found, same discipline as
    parse_confirmation.
    """
    summary_start = body.find("Order Summary")
    if summary_start == -1:
        return []
    window = body[summary_start:]

    # Same line-by-line adjacency walk as parse_confirmation, for the same
    # reason: a bridging regex over an unconstrained gap mismatched a
    # blank separator row as the name in the first draft of that parser.
    out: list[NoPriceLine] = []
    pending_name: Optional[str] = None
    pending_sku: Optional[str] = None
    for line in window.splitlines():
        if pending_sku is not None:
            # Waiting on a Qty for a SKU already seen on its own line (see
            # _SKU_ONLY_ROW_RE above) -- must be the very next line, or
            # this row is one of the mangled duplicate renderings and gets
            # dropped rather than mis-paired.
            qty_m = _QTY_ONLY_ROW_RE.match(line)
            if qty_m and pending_name:
                out.append(NoPriceLine(raw_product_text=pending_name, external_sku=pending_sku, quantity=int(qty_m.group("qty"))))
            pending_name = None
            pending_sku = None
            continue
        sku_m = _CANCEL_SKU_ROW_RE.search(line)
        if sku_m:
            if pending_name:
                out.append(NoPriceLine(raw_product_text=pending_name, external_sku=sku_m.group("sku"), quantity=int(sku_m.group("qty"))))
            pending_name = None
            continue
        if pending_name is not None:
            sku_only_m = _SKU_ONLY_ROW_RE.match(line)
            if sku_only_m:
                pending_sku = sku_only_m.group("sku")
                continue
        name_m = _NAME_ROW_RE.match(line)
        if name_m:
            text = name_m.group(1).strip()
            pending_name = text if text else None

    return out


def parse_cancelled_lines(body: str) -> list[NoPriceLine]:
    """
    Extract the item(s) actually canceled, from a CANCELLED_FULL-classified
    email -- despite that name, PC has only ONE cancellation subject
    template ("Your order has been canceled") for both a whole-order and a
    partial cancellation; the body itself says so explicitly ("the below
    item(s) ... The rest of the items (if any) in your order will be
    processed"). classify.py's CANCELLED_FULL label is a SUBJECT-ONLY
    guess and must never be trusted here -- callers have to compare this
    list against the order's full original line set (from its
    confirmation, matched by external_sku) to tell a partial cancellation
    from a complete one. Verified against 2 real cancellation emails,
    orders P0038894998 and P0038918210 -- both list all 3 of that order's
    original lines, so neither fixture alone proves the partial case, but
    the body's own copy ("if any") confirms partial cancellation is a
    real possibility this template covers.
    """
    return _extract_no_price_lines(body)


def parse_shipped_lines(body: str) -> list[NoPriceLine]:
    """
    For a SHIPPED email: the item(s) covered by THIS shipping notice --
    verified against order P0038927021 (thread 1a0a5ce2cc85a81b), whose
    SKU/Qty rows are byte-identical in shape to the cancellation
    template's, just with an extra space around "#" (already tolerated
    by _CANCEL_SKU_ROW_RE's \\s*).

    NOTE this is not necessarily every line in the order -- the
    confirmation email mentions a per-shipment "Fulfillment ID", implying
    split shipments are possible (unverified: no multi-shipment order has
    been seen yet, since every real order checked so far shipped whole).
    Callers should treat this as "these specific lines shipped", not "the
    whole order shipped".
    """
    return _extract_no_price_lines(body)
