"""
parse_target.py
----------------
Turns a Target confirmation email body into cart-line claim dicts.

STRUCTURE, verified against real mail (order 912003448396552, thread
19e4e800e1e6f6c5; and 912002032160334, thread 1937bfe249810a76): unlike
Pokémon Center, Target's confirmation has NO per-line SKU and, so far,
NEVER more than one distinct product per cart -- confirmed twice (0 of 183
Target orders in Cache share an order number, and 0 of 6 real confirmation
emails, including the two largest by byte size chosen specifically to find
a counterexample, showed more than one distinct product). So this parser
returns at most one Line; app/matching.py's cart/line matcher stays
retailer-agnostic regardless, for Pokémon Center's sake.

THE UPSELL TRAP: every real confirmation carries a "Take another look" /
"Perfect pairings" block listing unrelated products with prices, styled
identically to the real line. The real line sits at a fixed position --
directly after the shipping "Delivers to:" block and before "Order
Summary" -- which is exactly what bounds the search window below. Never
scan past "Order Summary" for a product line; that section is code
(Subtotal/Discounts/Delivery/Taxes/Total for the SAME line already
captured), not more cart lines, and if the upsell block ever moved above
"Order Summary" position-bounding still holds.

Real-format quirks fixed on the two orders checked:
  - "Order Summary" is followed by "Subtotal (N items)" where N is the
    total QUANTITY, not a line count -- never treat it as "N products".
  - Target Circle Card discounts (a %-off line) reduce the stated total
    but not the line's own price; net line cost still has to come from
    Subtotal + Discounts + tax, same allocation idea as Pokémon Center,
    simplified to one line since there's only ever one.
"""

import re
from dataclasses import dataclass
from typing import Optional

_ORDER_NUMBER_RE = re.compile(r"Order #(\S+)")
_PLACED_RE = re.compile(r"Placed ([A-Za-z]+ \d{1,2}, \d{4})")

# The one real cart line: name, then "Qty: N" and "$X.XX / ea" nearby (not
# necessarily adjacent -- "Arrives ..." / "Rate & review" rows can sit
# between them in the real mail). Bounded search, see parse_confirmation.
_QTY_RE = re.compile(r"Qty\s*:\s*(\d+)")
_PRICE_EACH_RE = re.compile(r"\$([\d,]+\.\d{2})\s*/\s*ea")

_SUBTOTAL_RE = re.compile(r"Subtotal\s*\(\d+\s*(?:items?|or more items)\)\s*\n*\$?([\d,]+\.\d{2})", re.I)
_DISCOUNT_RE = re.compile(r"-\$([\d,]+\.\d{2})")
_TAX_RE = re.compile(r"Estimated taxes.*?\$([\d,]+\.\d{2})", re.S)
_TOTAL_RE = re.compile(r"\bTotal\s*\n*\$?([\d,]+\.\d{2})", re.I)

# "United Parcel Service Tracking # 1ZWY06570303836010" -- verified against
# 2 real shipping emails (orders 902003598796944 and 912003686512081,
# threads 1a0ac89cbf63d317 and 1a0ac7c4d29db3a8). The carrier name itself
# is intentionally not captured: carrier is derived from the tracking
# number's own FORMAT elsewhere (see backend/app/tracking.py), same
# discipline as models.py's Order.carrier column -- re-deriving it here
# from the retailer's free-text label would be a second, possibly
# conflicting source of truth for the same fact.
_TARGET_TRACKING_RE = re.compile(r"Tracking #\s*([A-Za-z0-9]+)")

# For a CANCELLED_PARTIAL email, where the order number is NOT in the
# subject (see classify.py -- only the last 3-4 digits are). Two real
# formats observed for "Order #" in this template, verified against
# orders 102002382211975 (2026, thread 19916e47671de66e) and 9180113030448
# (2022, thread 184398ef18c6cdde): sometimes the number sits directly
# after "Order #" on one line, sometimes "Order #" is itself the hyperlink
# and the number is the anchor text on the NEXT line, with a stray blank
# line between -- the optional (?:https?://\S+\s*\n*\s*)? group tolerates
# the second shape without requiring it for the first. .search() takes
# only the first match, which is always this heading occurrence in both
# real orders checked, never the prose "your order #..." reference later
# in the body (which sometimes links to "View order details" instead of
# repeating the digits at all).
_CANCEL_ORDER_NUMBER_RE = re.compile(r"[Oo]rder #\s*\n*\s*(?:https?://\S+\s*\n*\s*)?(\d{9,20})")

# The "Canceled items" section of a CANCELLED_PARTIAL email: one product
# name, then "Qty: N" a couple of lines later (a URL line usually sits
# between them). Verified against the same 2 real orders as
# _CANCEL_ORDER_NUMBER_RE above -- identical shape in both, 4 years apart.
_CANCEL_QTY_RE = re.compile(r"Qty\s*:\s*(\d+)")


@dataclass
class Line:
    raw_product_text: str
    quantity: int
    unit_price: float  # tax/discount-inclusive, see module docstring


@dataclass
class NoPriceLine:
    """Shared by parse_cancelled_lines and parse_shipped_line -- neither
    the "Canceled items" section nor the shipping notice states a price,
    only a product name and quantity (nothing to allocate: knowing what
    to reduce, or what shipped, is the whole point; what it cost was
    already recorded by the confirmation)."""

    raw_product_text: str
    quantity: int


def _to_float(money: str) -> float:
    return float(money.replace(",", ""))


def parse_confirmation(body: str) -> list[Line]:
    """
    Returns 0 or 1 Line -- see module docstring on why never more. Empty
    list (not a raised error) on any structural surprise, same discipline
    as parse_pokemoncenter: a template change should read as "0 lines,
    go look", not crash a sync pass.
    """
    order_start = body.find("Order total")
    summary_start = body.find("Order Summary")
    if order_start == -1 or summary_start == -1 or summary_start <= order_start:
        return []
    window = body[order_start:summary_start]

    # The product name is the line immediately before "Qty:" in this
    # window -- found empirically by locating the Qty marker and walking
    # backward to the nearest non-empty preceding text line, rather than
    # assuming fixed adjacency (the real mail has extra rows -- delivery
    # estimate, review prompts -- whose exact position varies by order
    # status, unlike Pokémon Center's clean 2-row-per-line table).
    qty_m = _QTY_RE.search(window)
    price_m = _PRICE_EACH_RE.search(window)
    if not qty_m or not price_m:
        return []

    name = None
    for line in window[: qty_m.start()].splitlines()[::-1]:
        text = line.strip()
        if not text or text.startswith("http") or text in {"Rate & review", "Write a review"}:
            continue
        name = text
        break
    if not name:
        return []

    qty = int(qty_m.group(1))
    price_each = _to_float(price_m.group(1))
    extended = price_each * qty

    # Bounded to the Order Summary block specifically -- from "Order
    # Summary" to "Need to make changes?", present verbatim in both real
    # orders checked, right after the payment-method line. NOT searched
    # unbounded across the whole body: a discount-badge price in a future
    # "Take another look" upsell block (plausible for Target, even though
    # neither real sample happened to have one) would otherwise be summed
    # into this order's discount by the earlier, looser version of this
    # function -- confirmed as a real design gap during review, fixed
    # before it ever mattered on live data.
    summary_end = body.find("Need to make changes", summary_start)
    summary_window = body[summary_start: summary_end if summary_end != -1 else len(body)]

    subtotal_m = _SUBTOTAL_RE.search(summary_window)
    tax_m = _TAX_RE.search(summary_window)
    total_m = _TOTAL_RE.search(summary_window)
    discount_ms = _DISCOUNT_RE.findall(summary_window)
    tax = _to_float(tax_m.group(1)) if tax_m else 0.0
    discount = sum(_to_float(d) for d in discount_ms)

    # Cross-check against the stated Subtotal: this is a single line by
    # construction (see module docstring), so extended MUST equal the
    # cart subtotal. A mismatch means either Target sent a real multi-line
    # cart for the first time, or the name/qty/price walk above landed on
    # the wrong row -- either way, returning a confidently wrong single
    # line is worse than surfacing nothing for a human to look at.
    if subtotal_m and abs(_to_float(subtotal_m.group(1)) - extended) > 0.01:
        return []

    # Single line, so no proportional split needed -- the whole cart's
    # tax and discount belong to this one product.
    unit_price = (extended + tax - discount) / qty if qty else price_each

    # Second, independent cross-check against the stated grand Total, when
    # present. Same reasoning: a stale/missing discount or tax match would
    # otherwise ship a wrong cost_basis with nothing catching it.
    if total_m and abs(_to_float(total_m.group(1)) - unit_price * qty) > 0.01:
        return []

    return [Line(raw_product_text=name, quantity=qty, unit_price=unit_price)]


def parse_order_number(body: str) -> Optional[str]:
    m = _ORDER_NUMBER_RE.search(body)
    return m.group(1) if m else None


def parse_purchased_at(body: str) -> Optional[str]:
    m = _PLACED_RE.search(body)
    return m.group(1) if m else None


def parse_tracking_number(body: str) -> Optional[str]:
    """For a SHIPPED email. Order number for these comes from
    parse_order_number -- the "Order #NNN" heading is plain, unlinked text
    in this template (unlike the cancellation templates; see
    _CANCEL_ORDER_NUMBER_RE), verified against 2 real shipping emails."""
    m = _TARGET_TRACKING_RE.search(body)
    return m.group(1) if m else None


def parse_cancellation_order_number(body: str) -> Optional[str]:
    """For a CANCELLED_PARTIAL email only -- CANCELLED_FULL already gets
    its order number from the subject line (see classify.py), and that is
    the only reliable source for it: it happens to also find the right
    number in a real full-cancellation body (verified), but that body
    carries no per-line data at all, so there is nothing for a caller to
    do with parse_cancellation_order_number()'s result there that
    classify()'s subject-derived number doesn't already give it."""
    m = _CANCEL_ORDER_NUMBER_RE.search(body)
    return m.group(1) if m else None


def parse_cancelled_lines(body: str) -> list[NoPriceLine]:
    """
    For a CANCELLED_PARTIAL email: the specific item(s) actually canceled,
    from the "Canceled items" section. At most one Line, same invariant
    as parse_confirmation and for the same reason -- Target has never been
    observed to put more than one distinct product in one cart.

    UNVERIFIED, FLAGGED RATHER THAN GUESSED: whether the stated Qty here
    is always the line's FULL original quantity (so "partial" describes
    the cart -- the customer kept other items from a different line --
    while this one line is wholly cancelled) or can be a SUBSET of it (a
    genuine partial-quantity cancellation on one line, e.g. 3 ordered, 1
    cancelled, 2 kept). Neither of the 2 real fixtures checked came with
    its original confirmation email to compare against, so this could not
    be verified either way. A caller must NOT assume "the matched line's
    status becomes cancelled" is always correct -- if the returned
    quantity is ever less than the matched order's own quantity, treat it
    as the unresolved case above and leave the line alone rather than
    guess, same discipline as every reconciliation check in this module.

    Returns [] when the section marker isn't found or no name/Qty pair
    follows it -- same discipline as parse_confirmation and
    parse_pokemoncenter.parse_cancelled_lines: a template surprise should
    read as "nothing parsed, go look", never crash a sync pass.
    """
    cancel_start = body.find("Canceled items")
    if cancel_start == -1:
        return []
    window = body[cancel_start:]

    # First non-blank, non-URL line after the marker is the product name
    # -- same "walk forward past link/spacer rows" approach as
    # parse_confirmation's backward walk for the same reason: the real
    # mail has a variable number of link lines here, not fixed adjacency.
    # No offset-tracking needed to search past it: a product name never
    # contains "Qty:" itself, so searching the whole window still lands
    # on the one real Qty line, not the name.
    name = None
    for line in window.splitlines():
        text = line.strip()
        if not text or text.startswith("http") or text == "Canceled items":
            continue
        name = text
        break

    if not name:
        return []

    qty_m = _CANCEL_QTY_RE.search(window)
    if not qty_m:
        return []

    return [NoPriceLine(raw_product_text=name, quantity=int(qty_m.group(1)))]


def parse_shipped_line(body: str) -> Optional[NoPriceLine]:
    """
    For a SHIPPED email (both real templates -- "we're getting ready to
    ship your order" and "your order arrives today/tomorrow", which
    classify() maps to the same EmailKind; see classify.py's
    _TARGET_ARRIVES_SOON comment): the product name and quantity, needed
    so this claim carries SOMETHING app/matching.py can key on (a bare
    tracking number alone gives match_line() no identifying signal at
    all).

    Same backward-walk-from-Qty technique as parse_confirmation, verified
    this generalizes across both real shipped templates despite their
    different surrounding copy ("Track status" / "Looking for your
    receipt?" vs "Arriving today" / "Any issues with your order?"): in
    both, the product name is the line immediately before the FIRST
    "Qty:" in the body, with no other "Qty:" occurrence anywhere earlier
    -- .search() takes that first match, so content any distance AFTER
    it is already irrelevant with or without a bound.

    BOUNDED to end at whichever of those two known end-markers actually
    appears (whichever comes first, if either does). This does NOT guard
    against an upsell block placed AHEAD of the real line -- nothing
    could, short of a marker this function doesn't have that reliably
    starts right before the real line across template variants, which no
    real sample has offered yet (unlike parse_confirmation's "Order
    total"..."Order Summary" window, which brackets the real line on
    BOTH sides). What the bound DOES protect: if the real line's own Qty
    is ever missed for some other reason (a malformed row, a third
    template shape), an unbounded search would silently fall through to
    the NEXT "Qty:" it finds -- which, in a future template, could be an
    upsell item's, past one of these two markers, attaching a wrong
    product/quantity with nothing to catch it. Bounded, that same miss
    returns None instead: refuses to guess, same discipline as every
    reconciliation check in this module, just for a case with no number
    to reconcile against.
    """
    end = min(
        (i for i in (body.find("Looking for your receipt?"), body.find("Any issues with your order?")) if i != -1),
        default=len(body),
    )
    window = body[:end]

    qty_m = _QTY_RE.search(window)
    if not qty_m:
        return None

    name = None
    for line in window[: qty_m.start()].splitlines()[::-1]:
        text = line.strip()
        if not text or text.startswith("http"):
            continue
        name = text
        break
    if not name:
        return None

    return NoPriceLine(raw_product_text=name, quantity=int(qty_m.group(1)))
