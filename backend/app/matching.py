"""
matching.py
-----------
Decides whether an incoming message describes a purchase Cache already has
a row for -- and if so, WHICH row.

WHY THIS IS NOT ONE LOOKUP: deduplication today is
UNIQUE(source_id, external_id), which only catches the same message twice
from the same source. It cannot see that a Discord checkout webhook and a
Pokemon Center confirmation email describe the same purchase, so without
this module every order seen by both sources becomes two rows -- double
spend, and double-created inventory units.

THE SHAPE, verified against real data rather than assumed:

  A cart is not a row.  130 of 348 numbered orders (37%) share an order
  number with another order; carts run up to four lines. The bot logs a
  multi-item cart as one Discord message PER LINE, while the retailer
  sends ONE email for the whole cart. So the relationship is one email to
  many order rows, and matching on the order number alone would collapse a
  three-line cart into a single row -- destroying exactly the inventory
  count this design exists to protect.

So identity has two levels:

  cart  (retailer, normalized order_number)  -- which purchase
  line  SKU, else product identity + unit price  -- which line of it

A `purchases` parent table would express that hierarchy more honestly, and
was deliberately rejected: partial cancellations and split shipments are
both real (Pokemon Center's cancellation mail says "The rest of the items
(if any) in your order will be processed", and its shipping mail carries a
per-shipment "Fulfillment ID"), which means STATE has to stay line-level.
What is genuinely cart-level -- tax, shipping, totals -- is allocatable
rather than stateful. So the cart stays a derived grouping, and every
existing query path keeps working untouched.
"""

import re
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app import models

# Real formats seen in this user's data and mail: Target's bare 15 digits,
# Pokemon Center's "P0038875758", and one row that arrived as
# "#123456789012345". Pokemon Center's email body prints the number
# character-identical to what the bot already stored, so normalization is
# about defending against punctuation and case drift, not reconciling two
# different schemes.
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def normalize_order_number(value: Optional[str]) -> Optional[str]:
    """Strip punctuation and case so "#P0038875758 " and "p0038875758"
    are the same cart. Returns None for anything with no alphanumeric
    content, which must never match."""
    if not value:
        return None
    cleaned = _NON_ALNUM.sub("", value).upper()
    return cleaned or None


def is_matchable(status: Optional[str], order_number: Optional[str]) -> bool:
    """
    Whether a record can participate in cross-source matching at all.

    Failed checkouts never can, and that is correct rather than a gap:
    measured across real data, 0 of 257 'failed' orders carry an order
    number, because no order was ever created for them. They exist in
    Discord and nowhere else, permanently. Reaching for a fuzzy match on
    those would invent links between unrelated attempts.
    """
    if status == "failed":
        return False
    return normalize_order_number(order_number) is not None


def find_cart(
    db: Session,
    user_id: str,
    retailer: Optional[str],
    order_number: Optional[str],
) -> list[models.Order]:
    """
    Every order row already recorded for one real-world cart.

    Keyed on retailer as well as number because order numbers are only
    unique WITHIN a retailer -- Target's 15-digit sequence and Pokemon
    Center's P-prefixed one could collide in principle. Retailer is
    compared on the normalized `retailer` field, not raw `site`, since
    that is the value both ingestion paths already agree on (Discord
    derives it from a URL, email will derive it from a sender domain --
    see retailers.display_name).
    """
    key = normalize_order_number(order_number)
    if not key or not retailer:
        return []

    candidates = (
        db.query(models.Order)
        .filter(models.Order.user_id == user_id)
        .filter(models.Order.retailer == retailer)
        .filter(models.Order.order_number.isnot(None))
        .all()
    )
    # Normalized in Python rather than SQL: SQLite has no regex replace,
    # and a cart is a handful of rows out of a few hundred.
    return [o for o in candidates if normalize_order_number(o.order_number) == key]


# Sources that emit one message per ORDER EVENT rather than per cart line:
# email sends a confirmation, then a shipping notice, then perhaps a
# cancellation, all describing the SAME lines. Its own earlier message is
# the one a later message must find and amend -- blocking that would make
# a cancellation create a second row instead of cancelling the order it
# refers to.
#
# Defined as the EXCEPTION, not the rule, so the default falls the safe
# way: every other source (a checkout channel, a spreadsheet import, a
# manual entry, and anything added later) is treated as emitting one
# message per line, and its own lines are never merged into each other.
# Wrongly creating a second row is visible and fixable; wrongly merging
# two lines silently destroys a unit the user actually bought.
PER_ORDER_SOURCE_TYPES: frozenset[str] = frozenset({"email_account"})


def emits_one_message_per_line(source_type: Optional[str]) -> bool:
    """Whether a source splits one cart across separate messages, so that
    two of its own messages are two different purchases. True for
    everything except the per-order sources above, including unknown and
    missing types."""
    return (source_type or "") not in PER_ORDER_SOURCE_TYPES


def match_line(
    cart: Iterable[models.Order],
    exclude_source_id: Optional[str] = None,
    sku: Optional[str] = None,
    unit_price: Optional[float] = None,
    quantity: Optional[int] = None,
    product_id: Optional[str] = None,
) -> Optional[models.Order]:
    """
    Pick which line of an already-identified cart an incoming claim
    describes, or None if it describes a line Cache has never seen.

    Pass `exclude_source_id` when the incoming message comes from a source
    that emits one message PER LINE -- see emits_one_message_per_line().
    Lines from that same source are then skipped entirely, before any rule
    runs, because two messages from one checkout channel are two different
    things bought together rather than one thing seen twice.

    Without that guard, real cart P0035996055 breaks: it holds four
    Discord lines priced 15.99, 15.99, 13.99, 13.99, so the second $15.99
    message would match the first and merge into it, silently destroying a
    unit the user actually bought. Verified against live data.

    Leave it None for a source that emits one message per ORDER EVENT
    (email), where the second message is precisely the one that must find
    and amend what the first created.

    PRICE CANNOT BE THE CROSS-SOURCE KEY, which is the one place this
    departs from products.find_merge_suggestions(). That function matches
    a Discord line to a SPREADSHEET line, and both carry the pre-tax cart
    price, so requiring price agreement is safe there. An email carries
    the price actually charged -- $65.31 where Discord saw $59.99 -- so
    the very correction email exists to deliver is what would make a
    price-keyed match fail. Quantity survives tax; price does not.

    Tried in descending confidence:

      1. SKU. The retailer's own identifier for the line, and by far the
         strongest key -- every Pokemon Center email carries one per line
         ("SKU #: 10-10449-122"). Exact, no heuristics.
      2. Product identity plus quantity. The workhorse for Discord
         against email: both name the same product and agree on how many,
         and neither figure moves when tax is applied.
      3. Product identity alone, but ONLY when exactly one line in the
         cart carries that product. Ambiguity here means the cart holds
         two lines of the same item, so guessing would be a coin flip.
      4. Unit price plus quantity, for a claim whose product can't be
         resolved yet. Still useful between two sources that quote the
         same price (Discord against spreadsheet import).

    KNOWN LIMIT, to settle in Phase 2 against real mail: a cart can hold
    two Discord lines of the same product at quantity 1 each (real
    example, P0035996055) while the retailer's email states that product
    once at quantity 2. That is one email line against two order rows, and
    rule 3 will attach it to the first. Whether Pokemon Center actually
    aggregates same-SKU lines this way is unverified -- the confirmation
    read so far listed three distinct SKUs, so the case never arose.

    Returning None is a real answer, not a failure: an email line that
    matches nothing is a cart line Discord never logged, and the caller
    should CREATE it. That is email filling a gap, which is one of the
    reasons to ingest it at all.

    A cart can legitimately hold two indistinguishable lines -- real
    example, cart P0035996055 holds two at $15.99 and two at $13.99. Those
    units are interchangeable, so matching either is correct; this returns
    the first unclaimed one rather than pretending the ambiguity matters.
    """
    # Drop same-source lines before any rule runs, so no amount of price
    # or SKU agreement can fold two lines of one cart together.
    rows = [
        o for o in cart if exclude_source_id is None or o.source_id != exclude_source_id
    ]
    if not rows:
        return None

    if sku:
        for order in rows:
            if order.external_sku and order.external_sku == sku:
                return order

    if product_id is not None:
        same_product = [o for o in rows if o.product_id == product_id]
        if quantity is not None:
            for order in same_product:
                if (order.quantity or 1) == quantity:
                    return order
        # Unambiguous product match: exactly one line in this cart is that
        # item, so it is the line regardless of what the price says.
        if len(same_product) == 1:
            return same_product[0]

    if unit_price is not None:
        for order in rows:
            if not _same_price(order.unit_price, unit_price):
                continue
            if quantity is not None and (order.quantity or 1) != quantity:
                continue
            return order

    return None


def _same_price(a: Optional[float], b: Optional[float]) -> bool:
    """Money compared to the cent. Stored as float (SQLite has no decimal),
    so a bare == would miss on representation noise like 59.99 vs
    59.990000000000002."""
    if a is None or b is None:
        return False
    return abs(a - b) < 0.005
