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
import unicodedata
from typing import Iterable, Mapping, Optional

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


# Words that appear in nearly every product title and so say nothing about
# WHICH product it is, plus the "Styles May Vary" boilerplate a retailer
# prints on blind items. Dropped before comparing two names.
_NAME_STOPWORDS = frozenset(
    "pokemon tcg trading card cards game tading the of and or a an in with for "
    "styles style may vary".split()
)
_NAME_TOKEN = re.compile(r"[a-z0-9]+")

MIN_SHARED_NAME_TOKENS = 2
MIN_NAME_OVERLAP = 0.5

# "{message_id}:{kind}[:{line_index}]" -- see email_ingest/ingest.py.
_EMAIL_KIND = re.compile(r":(confirm|ship|arrived|cancel\w*)(?::\d+)?$")


def name_tokens(text: Optional[str]) -> frozenset[str]:
    """The distinguishing words of a product name: accents folded, lower
    cased, boilerplate and bare numbers removed ("EX Box 2" keeps "ex" and
    "box"; the 2 is a listing counter, not part of the product)."""
    if not text:
        return frozenset()
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return frozenset(
        t
        for t in _NAME_TOKEN.findall(folded.lower())
        if t not in _NAME_STOPWORDS and not t.isdigit()
    )


def name_affinity(a: Optional[str], b: Optional[str]) -> tuple[int, float]:
    """(shared distinguishing words, shared / the shorter name's word count).
    Overlap is measured against the SHORTER name because the two texts for
    one line differ in specificity, not in kind: a generic listing title is
    a near-subset of the specific title the retailer prints at shipment."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0, 0.0
    shared = len(ta & tb)
    return shared, shared / min(len(ta), len(tb))


def claim_kind(external_id: Optional[str], source_type: Optional[str]) -> Optional[str]:
    """Which lifecycle event a message reports, for the two that name a
    product: 'confirm' (a placed order -- every non-email source counts as
    one) or 'ship'. Arrivals and cancellations return None."""
    if (source_type or "") not in PER_ORDER_SOURCE_TYPES:
        return "confirm"
    found = _EMAIL_KIND.search(external_id or "")
    kind = found.group(1) if found else None
    return kind if kind in ("confirm", "ship") else None


def match_line(
    cart: Iterable[models.Order],
    exclude_source_id: Optional[str] = None,
    sku: Optional[str] = None,
    unit_price: Optional[float] = None,
    quantity: Optional[int] = None,
    product_id: Optional[str] = None,
    name: Optional[str] = None,
    kind: Optional[str] = None,
    claimed: Optional[Mapping[str, set[str]]] = None,
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
      5. LAST RESORT: exactly one line left in the cart, and the claim
         carries no identifying signal at all (sku, product_id, and
         unit_price all None). Needed for Target's full-cancellation
         email, which states only "order #NNN was canceled" -- the
         retailer's own template gives no per-line detail to key on,
         unlike Pokemon Center's cancellation (always carries a SKU per
         affected line, matched by rule 1) or Target's own PARTIAL
         cancellation (carries a product name, resolved to product_id).
         This is not a guess: with zero signal AND exactly one candidate,
         that candidate is the only thing the claim COULD describe. Never
         fires for an ambiguous cart (rule silently does nothing when
         len(rows) != 1), so a genuinely multi-line PC cart missing a SKU
         is left unmatched rather than blindly attached to whichever line
         happens to be first -- unmatched is visible and fixable, a wrong
         merge is not.

      6. NAME AFFINITY, for a cart line whose text changes between events.
         A retailer's confirmation prints a marketing title ("Pokemon 30th
         Anniversary EX Box 2", "Scarlet Violet Elite Trainer Box") and its
         shipping notice prints the specific one ("...30th Celebration
         Greninja ex Box", "...Prismatic Evolutions Elite Trainer Box").
         Those resolve to DIFFERENT products, so rules 2-3 can never pair
         them, and the ship notice has no price or SKU for rules 1 and 4 --
         which is how one purchase kept splitting into a row per email.
         The claim adopts a line when ALL of these hold:
           - it carries a name and is a confirm or ship event
           - the cart has no line of its own product already (else rules
             2-3 were the right answer and failing them means "different
             line")
           - the line has no claim yet of the same kind from ANY source
             (a second Discord line, or a second ship for the same line
             under a different name, is another purchase, not this).
             The observed mismatch is always confirm-vs-ship, so a
             confirm-vs-confirm pair is left to rules 1-4 alone
           - quantities agree when both are known
           - the names share >= 2 distinguishing words covering >= half of
             the shorter name
           - exactly one line scores best; a tie leaves it unmatched
         A wrong merge destroys a unit, an unmatched claim only shows as a
         visible duplicate, so every ambiguity resolves to unmatched.

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

    # Rule 6 -- see docstring.
    if name and kind is not None and claimed is not None:
        already_has_own_row = product_id is not None and any(
            o.product_id == product_id for o in rows
        )
        if not already_has_own_row:
            scored = []
            for order in rows:
                if kind in claimed.get(order.id, ()):
                    continue
                if (
                    quantity is not None
                    and order.quantity is not None
                    and order.quantity != quantity
                ):
                    continue
                shared, overlap = name_affinity(name, order.raw_product_text)
                if shared >= MIN_SHARED_NAME_TOKENS and overlap >= MIN_NAME_OVERLAP:
                    scored.append(((shared, overlap), order))
            scored.sort(key=lambda s: s[0], reverse=True)
            if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
                return scored[0][1]

    # Rule 5 -- see docstring. Only when NOTHING was given to match on;
    # a claim that supplied a sku/product_id/unit_price and simply failed
    # to find an agreeing line must stay unmatched, not fall through here.
    if sku is None and product_id is None and unit_price is None and len(rows) == 1:
        return rows[0]

    return None


def _same_price(a: Optional[float], b: Optional[float]) -> bool:
    """Money compared to the cent. Stored as float (SQLite has no decimal),
    so a bare == would miss on representation noise like 59.99 vs
    59.990000000000002."""
    if a is None or b is None:
        return False
    return abs(a - b) < 0.005
