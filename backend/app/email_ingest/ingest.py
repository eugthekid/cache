"""
ingest.py
---------
Turns one email (subject + plaintext body + message id + received-at) into
zero or more OrderCreate-shaped claim dicts -- the pure "what does this
message assert" layer, sitting between imap_client (fetches raw mail) and
app/email_poller.py (turns each Claim into a real schemas.OrderCreate and
calls crud.ingest_order() directly -- no HTTP hop, since polling now runs
inside this same process). No I/O here at all, and deliberately no
backend import either (Claim.to_payload() returns a plain dict, not a
schemas.OrderCreate) -- keeping this package framework-free is what makes
it testable against the exact same captured fixtures the parser tests
already use, with no live mailbox and no backend needed.

DISPATCH IS BY (retailer, kind) FROM classify.classify(subject) -- never
guessed from the body. Built: CONFIRMATION, SHIPPED, CANCELLED_FULL,
CANCELLED_PARTIAL for Pokemon Center and Target, plus ARRIVED for Target
(2026-09-19 -- Target's own "items have arrived" email, same zero-
per-line-signal shape as its CANCELLED_FULL). Still unbuilt: Walmart
entirely (no parser exists yet), PC's ARRIVED (classify.py has no
subject pattern for one -- unclear PC even sends this kind), and
PAYMENT_PENDING for either retailer -- deliberately, not silently
mishandled: see cache-email-primary-architecture memory for why.

EXTERNAL_ID SCHEME: "{message_id}:{kind}[:{line_index}]". Stable across
re-processing the same message (a sent email's content and Message-ID
never change, so the same body parses to the same lines in the same
order every time) and unique per claim within one message -- which
matters because a multi-line Pokemon Center confirmation is ONE message
but N separate claims, each needing its own row in ingested_messages
(see backend/app/models.py's IngestedMessage and app/matching.py's
"one email to many order rows" note). A single-claim event (Target's
confirmation/shipped/cancellation, capped at one line by the retailer's
own single-line-cart invariant; a Target full-cancellation, which has no
line data at all) skips the numeric suffix -- there is only ever one.
"""

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Optional

from . import parse_pokemoncenter as pc
from . import parse_target as target
from .classify import Classification, EmailKind, Retailer, classify

# Both retailers' "Month DD, YYYY" purchase-date strings share this exact
# format (parse_pokemoncenter.parse_purchased_at's "Date Ordered: July 15,
# 2026" and parse_target.parse_purchased_at's "Placed May 22, 2026") --
# one shared parser, not two copies.
_DATE_FORMAT = "%B %d, %Y"


@dataclass
class Claim:
    """One line of backend/app/schemas.py's OrderCreate -- everything
    except source_id, which api_client.py fills in once it has looked up
    or created the Source row. Kept as a dataclass rather than a plain
    dict so a typo'd field name fails at construction, not silently as a
    dropped key in a JSON payload."""

    external_id: str
    status: str
    site: str
    order_number: Optional[str] = None
    raw_product_text: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    external_sku: Optional[str] = None
    tracking_number: Optional[str] = None
    shipping_status: str = "not_shipped"
    tracking_detail: Optional[str] = None
    ship_to_address: Optional[str] = None
    purchased_at: Optional[str] = None
    occurred_at: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def _to_iso(raw_date: Optional[str], fmt: str) -> Optional[str]:
    if not raw_date:
        return None
    try:
        return datetime.strptime(raw_date, fmt).isoformat()
    except ValueError:
        # A retailer template tweak breaking this should mean "this one
        # claim loses its purchased_at", not "the whole message fails to
        # ingest" -- occurred_at still carries a real timestamp
        # regardless (see build_claims), so claim resolution has
        # SOMETHING to order by even without this.
        return None


def _occurred_at_iso(received_at: Optional[datetime]) -> Optional[str]:
    if received_at is None:
        return None
    return received_at.isoformat()


def parse_email_date(raw_date_header: str) -> Optional[datetime]:
    """Wraps email.utils.parsedate_to_datetime with the same
    never-raise-on-a-malformed-header discipline as everything else in
    this package -- a missing or garbled Date header should degrade to
    "no occurred_at claim", not abort ingestion of an otherwise-good
    message."""
    if not raw_date_header:
        return None
    try:
        return parsedate_to_datetime(raw_date_header)
    except (TypeError, ValueError):
        return None


def build_claims(
    subject: str, body: str, message_id: str, received_at: Optional[datetime]
) -> list[Claim]:
    """The one entry point imap_client's output feeds into. Never raises:
    an unrecognized or malformed message returns [] rather than aborting
    a whole poll cycle over one bad email."""
    classification = classify(subject)
    if classification.retailer is None or classification.kind == EmailKind.UNRECOGNIZED:
        return []

    occurred_at = _occurred_at_iso(received_at)

    if classification.retailer == Retailer.POKEMON_CENTER:
        return _pc_claims(classification, body, message_id, occurred_at)
    if classification.retailer == Retailer.TARGET:
        return _target_claims(classification, body, message_id, occurred_at)
    # Retailer.WALMART: no parser built yet (see module docstring).
    return []


def _pc_claims(
    classification: Classification, body: str, message_id: str, occurred_at: Optional[str]
) -> list[Claim]:
    site = Retailer.POKEMON_CENTER.value
    order_number = pc.parse_order_number(body)
    purchased_at = _to_iso(pc.parse_purchased_at(body), _DATE_FORMAT)

    if classification.kind == EmailKind.CONFIRMATION:
        lines = pc.parse_confirmation(body)
        ship_to_address = pc.parse_ship_to_address(body)
        return [
            Claim(
                external_id=f"{message_id}:confirm:{i}",
                status="success",
                site=site,
                order_number=order_number,
                raw_product_text=line.raw_product_text,
                quantity=line.quantity,
                unit_price=line.unit_price,
                external_sku=line.external_sku,
                ship_to_address=ship_to_address,
                purchased_at=purchased_at,
                occurred_at=occurred_at,
            )
            for i, line in enumerate(lines)
        ]

    if classification.kind == EmailKind.SHIPPED:
        tracking_number = pc.parse_tracking_number(body)
        lines = pc.parse_shipped_lines(body)
        if lines:
            return [
                Claim(
                    external_id=f"{message_id}:ship:{i}",
                    status="success",
                    site=site,
                    order_number=order_number,
                    raw_product_text=line.raw_product_text,
                    quantity=line.quantity,
                    external_sku=line.external_sku,
                    tracking_number=tracking_number,
                    shipping_status="in_transit" if tracking_number else "not_shipped",
                    purchased_at=purchased_at,
                    occurred_at=occurred_at,
                )
                for i, line in enumerate(lines)
            ]
        # No per-line data parsed (a template hiccup -- PC carts, unlike
        # Target's, can genuinely be multi-line, so there's no safe way
        # to invent a line here) but a tracking number was still found:
        # emit ONE order-level claim rather than silently dropping real
        # tracking info. app/matching.py's rule 5 (zero signal + exactly
        # one candidate line) is what makes this land correctly on a
        # single-item order; on a genuinely multi-line cart it stays
        # unmatched -- a new, priceless row, same degraded-but-visible
        # outcome as any other unmatched claim, not silence.
        if tracking_number:
            return [
                Claim(
                    external_id=f"{message_id}:ship",
                    status="success",
                    site=site,
                    order_number=order_number,
                    tracking_number=tracking_number,
                    shipping_status="in_transit",
                    occurred_at=occurred_at,
                )
            ]
        return []

    if classification.kind == EmailKind.CANCELLED_FULL:
        # Despite the name, this may be a partial cancellation -- see
        # parse_pokemoncenter.parse_cancelled_lines' docstring. Each
        # returned line still only cancels the SPECIFIC sku it names
        # (via app/matching.py's SKU rule, its strongest), so an
        # over-broad CANCELLED_FULL label here never risks cancelling a
        # line this email didn't actually mention.
        lines = pc.parse_cancelled_lines(body)
        return [
            Claim(
                external_id=f"{message_id}:cancel:{i}",
                status="cancelled",
                site=site,
                order_number=order_number,
                raw_product_text=line.raw_product_text,
                quantity=line.quantity,
                external_sku=line.external_sku,
                purchased_at=purchased_at,
                occurred_at=occurred_at,
            )
            for i, line in enumerate(lines)
        ]

    # EmailKind.ARRIVED / PAYMENT_PENDING: not built this pass.
    return []


def _target_claims(
    classification: Classification, body: str, message_id: str, occurred_at: Optional[str]
) -> list[Claim]:
    site = Retailer.TARGET.value

    if classification.kind == EmailKind.CONFIRMATION:
        order_number = classification.order_number or target.parse_order_number(body)
        purchased_at = _to_iso(target.parse_purchased_at(body), _DATE_FORMAT)
        lines = target.parse_confirmation(body)
        ship_to_address = target.parse_ship_to_address(body)
        return [
            Claim(
                external_id=f"{message_id}:confirm",
                status="success",
                site=site,
                order_number=order_number,
                raw_product_text=line.raw_product_text,
                quantity=line.quantity,
                unit_price=line.unit_price,
                ship_to_address=ship_to_address,
                purchased_at=purchased_at,
                occurred_at=occurred_at,
            )
            for line in lines
        ]

    if classification.kind == EmailKind.SHIPPED:
        # Subject carries the order number for every real SHIPPED-kind
        # template seen (both "getting ready to ship" and "arrives
        # today/tomorrow" -- see classify.py's _TARGET_ARRIVES_SOON
        # comment), so classification.order_number is preferred; the
        # body fallback exists only in case a future template drops it
        # from the subject.
        order_number = classification.order_number or target.parse_order_number(body)
        tracking_number = target.parse_tracking_number(body)
        line = target.parse_shipped_line(body)
        if line is None:
            return []
        return [
            Claim(
                external_id=f"{message_id}:ship",
                status="success",
                site=site,
                order_number=order_number,
                raw_product_text=line.raw_product_text,
                quantity=line.quantity,
                tracking_number=tracking_number,
                shipping_status="in_transit" if tracking_number else "not_shipped",
                occurred_at=occurred_at,
            )
        ]

    if classification.kind == EmailKind.CANCELLED_FULL:
        # No per-line data exists in this template at all (see
        # parse_target.py's module docstring) -- this claim relies on
        # app/matching.py's rule 5 (single unambiguous candidate, zero
        # identifying signal) to attach to the right row.
        order_number = classification.order_number
        return [
            Claim(
                external_id=f"{message_id}:cancel",
                status="cancelled",
                site=site,
                order_number=order_number,
                occurred_at=occurred_at,
            )
        ]

    if classification.kind == EmailKind.ARRIVED:
        # Same zero-per-line-signal shape as CANCELLED_FULL above -- the
        # subject carries the order number (classify.py), the body only
        # ever confirms delivery, never per-line detail worth the upsell-
        # block risk of parsing further. status="success" is a safe,
        # true assertion (an order that arrived was never a failure);
        # claims.py's sticky-cancelled rule already protects against this
        # wrongly reviving an order a same-or-stronger-authority claim
        # already marked cancelled.
        order_number = classification.order_number
        delivered_at = target.parse_delivered_at(body)
        return [
            Claim(
                external_id=f"{message_id}:arrived",
                status="success",
                site=site,
                order_number=order_number,
                shipping_status="delivered",
                tracking_detail=f"Delivered {delivered_at}" if delivered_at else "Delivered",
                occurred_at=occurred_at,
            )
        ]

    if classification.kind == EmailKind.CANCELLED_PARTIAL:
        # Two real subject shapes land here (see classify.py): the
        # "ending in NNNN" template carries only the last 3-4 digits in
        # the subject, so the full number has to come from the body --
        # but the "cancel items in order #NNNN" template (found live
        # 2026-09-21) gives the FULL number right in the subject, more
        # reliably than re-parsing it out of the body. Prefer the
        # subject-derived one when present, same pattern as
        # CONFIRMATION/SHIPPED above. Without an order_number this claim
        # can't be matched to anything (app/matching.find_cart requires
        # one), so materialize_order would create an ORPHANED "cancelled"
        # order with no way to connect it to the real cart it was meant
        # to cancel -- worse than surfacing nothing, same discipline as
        # every reconciliation check in the parsers this connects to.
        order_number = classification.order_number or target.parse_cancellation_order_number(body)
        if order_number is None:
            return []
        lines = target.parse_cancelled_lines(body)
        if not lines:
            return []
        line = lines[0]
        return [
            Claim(
                external_id=f"{message_id}:cancel",
                status="cancelled",
                site=site,
                order_number=order_number,
                raw_product_text=line.raw_product_text,
                quantity=line.quantity,
                occurred_at=occurred_at,
            )
        ]

    # EmailKind.ARRIVED / PAYMENT_PENDING: not built this pass.
    return []
