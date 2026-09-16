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


@dataclass
class Line:
    raw_product_text: str
    quantity: int
    unit_price: float  # tax/discount-inclusive, see module docstring


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
