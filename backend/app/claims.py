"""
claims.py
---------
Resolves an order's fields from the CLAIMS that several sources make about
the same purchase.

THE MODEL: an order is not a row owned by whichever source reported it
first. It is the current best resolution of every claim received about that
purchase -- a Discord checkout webhook, the retailer's confirmation email,
a later cancellation, a shipping notice, a spreadsheet row, the user's own
edit. Whichever message arrives first materializes the row; every message
after it amends the row rather than creating a second one.

WHY NOT "email is primary, Discord is secondary": that phrasing smuggles in
an arrival order the real world does not respect. Discord typically lands
within seconds and the confirmation minutes later, but resyncs, backfills
and full channel re-scans routinely deliver messages out of order, and a
Discord backfill must never revert a tax-inclusive price back to the cart
price it saw at checkout. So precedence lives HERE, in the field rules --
not in the pipeline.

THE RULE: authority beats recency; recency breaks ties within one source.
That second half is what makes a cancellation supersede a confirmation
without any special handling -- it is simply a later claim from the same
source.

Two properties this buys, both load-bearing:

  ORDER-INDEPENDENT  the same set of messages resolves to the same row in
                     any arrival sequence.
  IDEMPOTENT         replaying the log is safe. crud.rebuild_from_messages()
                     already replays stored payloads, so a time-based
                     last-write-wins would make rebuild non-deterministic:
                     replay in a different order, get a different price.

This module is deliberately DB-free and pure, so the whole resolution can
be tested against real payloads with no session and no fixtures.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

# Source.type -> the claim source whose authority applies. Anything not
# listed is treated as the weakest known source rather than crashing: a
# new ingestion type should degrade to "believed last", never to "believed
# first" by accident.
CLAIM_SOURCE_BY_TYPE = {
    "manual": "user",
    "email_account": "email",
    "discord_channel": "discord",
    "import": "import",
}

# Default authority, strongest first.
#
#   user     a correction the person made by hand. Always wins -- see
#            apply_overrides(), which enforces this a second time for edits
#            that never became messages.
#   email    the retailer speaking about its own transaction: the price
#            actually charged (with tax and shipping), whether the order
#            survived, where the package is.
#   discord  the checkout attempt: profile, module, site, cart price, and
#            every FAILED attempt, which email never sends mail about.
#   import   historical backfill. Weakest on purpose -- a spreadsheet of
#            what you remember should not override what a live source saw.
SOURCE_RANK: tuple[str, ...] = ("user", "email", "discord", "import")

# Per-field overrides, for the few fields where two sources both make a
# claim AND the default ranking is wrong.
#
# This map is nearly empty BY DESIGN, and that is the main reason the
# model stays simple: a source that never observes a field never claims
# it, so absence does almost all the precedence work. Email has no idea
# which bot or profile checked out; Discord cannot know a package shipped.
# Only genuinely contested fields need a line here.
FIELD_RANK: dict[str, tuple[str, ...]] = {
    # Both report this one. Discord's is the checkout instant, to the
    # second, taken from the message timestamp. The confirmation email's
    # "Date Ordered: July 15, 2026" is the same event at day granularity,
    # so email would lose real precision if it won by default.
    "purchased_at": ("user", "discord", "email", "import"),
}

# Order fields that participate in resolution. Everything absent from this
# set is either structural (id, user_id, source_id, external_id,
# created_at), derived elsewhere (carrier and the shipping-alert
# timestamps, owned by crud.sync_tracking_fields; product_id, owned by
# products.resolve_product), or storage for the claims themselves
# (raw_json, user_overrides).
CLAIMED_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "failure_reason",
        "raw_product_text",
        "profile",
        "site",
        "retailer",
        "module",
        "category",
        "quantity",
        "unit_price",
        "currency",
        "order_number",
        "order_url",
        "external_sku",
        "thumbnail_url",
        "shipping_status",
        "tracking_number",
        "estimated_delivery",
        "tracking_detail",
        "ship_to_label",
        "ship_to_address",
        "purchased_at",
    }
)

# Claimed fields that must come back as real datetimes. Payloads are JSON,
# so a stored claim carries these as ISO STRINGS (verified against live
# data: '2026-04-08 17:13:29.828000'), and handing that straight to the ORM
# would put a string where the column expects a datetime -- silently, until
# something tries to compare or format it. Note `estimated_delivery` is
# deliberately absent: models.py defines it as an ISO date string, not a
# datetime.
DATETIME_FIELDS: frozenset[str] = frozenset({"purchased_at"})

# Sorts before every real timestamp, for a claim whose source never told us
# when it happened.
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _coerce(field: str, value: Any) -> Any:
    """ISO string -> datetime for the temporal fields. Tolerates both the
    'T' and space separators, which is why fromisoformat is used rather
    than a fixed format string. An unparseable value is passed through
    untouched rather than dropped: losing a claim silently is worse than
    surfacing a bad one."""
    if field not in DATETIME_FIELDS or not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


@dataclass(frozen=True)
class Claim:
    """What one message asserts about one purchase.

    `fields` holds ONLY what the source actually observed. A key that is
    absent means "no opinion" -- never "set this to null". That
    distinction is the whole reason a Discord message, which carries no
    tracking number, cannot wipe the tracking number an email supplied.
    """

    source: str
    occurred_at: Optional[datetime]
    fields: dict[str, Any]


def claim_source_for(source_type: Optional[str]) -> str:
    """Map a Source.type onto its authority. Unknown types resolve to the
    weakest rank rather than raising -- see CLAIM_SOURCE_BY_TYPE."""
    return CLAIM_SOURCE_BY_TYPE.get(source_type or "", SOURCE_RANK[-1])


def _rank(field: str, source: str) -> int:
    order = FIELD_RANK.get(field, SOURCE_RANK)
    try:
        return order.index(source)
    except ValueError:
        # A source with no declared rank for this field is weaker than
        # every source that has one.
        return len(order)


def _as_aware(value: Optional[datetime]) -> datetime:
    """Naive datetimes come back from SQLite (it has no tz type), and
    comparing naive to aware raises. Treat naive as UTC, which is what
    everything in this app stores."""
    if value is None:
        return _EPOCH
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def build_claim(
    payload: dict,
    source_type: Optional[str],
    occurred_at: Optional[datetime] = None,
) -> Claim:
    """
    Turn a stored IngestedMessage payload into a Claim.

    Drops None values, so a payload that simply didn't carry a field makes
    no assertion about it (see Claim.fields), and drops anything outside
    CLAIMED_FIELDS so structural keys can't be "resolved" into the row.
    """
    fields = {
        key: _coerce(key, value)
        for key, value in (payload or {}).items()
        if key in CLAIMED_FIELDS and value is not None
    }
    return Claim(
        source=claim_source_for(source_type),
        occurred_at=occurred_at,
        fields=fields,
    )


def resolve(claims: Iterable[Claim]) -> dict[str, Any]:
    """
    Reduce many claims to the fields an order should actually carry.

    Returns ONLY fields some claim asserted. A field nobody claimed is
    absent from the result rather than present-and-None, so a caller can
    apply the result over an existing row without blanking data that no
    source happened to mention this time.
    """
    winners: dict[str, tuple[int, datetime, Any]] = {}

    # Sorted, not just iterated, so the caller's arrival order genuinely
    # cannot affect the outcome -- the order-independence property this
    # whole module exists to provide. Ties on (time, source) are broken by
    # taking the later claim below, which only matters when one source
    # asserts two different values at the very same instant.
    ordered = sorted(
        claims, key=lambda c: (_as_aware(c.occurred_at), c.source)
    )

    for claim in ordered:
        when = _as_aware(claim.occurred_at)
        for field, value in claim.fields.items():
            rank = _rank(field, claim.source)
            current = winners.get(field)
            if current is None:
                winners[field] = (rank, when, value)
                continue
            current_rank, current_when, _ = current
            # Stronger authority wins outright, whenever it arrived.
            # Equal authority falls back to the later claim -- which is
            # exactly how a cancellation email supersedes the confirmation
            # that preceded it, with no special-casing.
            if rank < current_rank or (rank == current_rank and when >= current_when):
                winners[field] = (rank, when, value)

    return {field: value for field, (_, _, value) in winners.items()}


def apply_overrides(
    resolved: dict[str, Any], overrides: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """
    Lay the user's own edits over a resolved result.

    Enforced separately from the authority ranking because a hand edit
    never passes through the message log -- PATCH /orders/{id} writes it
    straight to orders.user_overrides. Applying it last means a correction
    survives every future re-resolution, which is the difference between
    a ledger people trust and one that quietly undoes their fixes.
    """
    if not overrides:
        return dict(resolved)
    merged = dict(resolved)
    merged.update(
        {k: v for k, v in overrides.items() if k in CLAIMED_FIELDS}
    )
    return merged
