"""
backfill_overrides.py
---------------------
One-shot: capture edits the user made BEFORE orders.user_overrides existed.

Until now an edit went straight onto the order row via PATCH /orders/{id}
and left no trace of having been an edit. Claim resolution (app/claims.py)
derives an order's fields from its messages, so the first re-resolution
would quietly revert every one of those edits -- a hand-typed tracking
number, a manually corrected status -- back to whatever the source
originally said.

The recovery is exact rather than a guess: if a field on the row differs
from what resolving that order's own messages produces, nothing but a human
could have put it there. That difference IS the edit, so it is recorded
into user_overrides where the resolver will honour it from now on.

Verified against live data before writing: 14 orders carried real edits --
12 with UPS tracking numbers typed in by hand (payload said
shipping_status='not_shipped', tracking=None) and 2 hand-cancelled orders
(payload said status='success'). Run once, after the 191817c9784c
migration; safe to re-run, since a captured override then resolves to
itself and produces no further diff.
"""

from collections import defaultdict

from sqlalchemy.orm import Session

from app import claims, models, products, retailers


def _derived(resolved: dict) -> dict:
    """Re-apply the two transforms materialize_order() runs AFTER the
    payload is accepted, so this compares like with like. Without it every
    row would look edited on `retailer` (derived from `site`) and on
    `raw_product_text` (cleaned by products.display_name)."""
    out = dict(resolved)
    if "site" in out:
        out.setdefault("retailer", retailers.display_name(out["site"]))
    if out.get("raw_product_text"):
        out["raw_product_text"] = products.display_name(out["raw_product_text"])
    return out


def _is_truncation(claimed, actual) -> bool:
    """
    True when the row's value is the claim's value with the TIME thrown
    away -- midnight on the same calendar date.

    This is damage, not an edit, and the difference matters: a date-only
    <input type="date"> in the order editor round-trips purchased_at and
    silently drops the time, so an order edited to add a tracking number
    also loses the hour it was actually bought. Found on 15 real orders,
    all stamped 00:00 on a date whose payload carries a real timestamp
    (e.g. row 2026-08-28 00:00 vs payload 2026-08-28T09:04:01.464).

    Capturing that as a user override would freeze the wrong value
    forever. Skipping it lets resolution restore the true timestamp from
    the message, which is a genuine repair -- the UI bug itself still
    needs fixing separately, or it will just do this again.
    """
    if not (hasattr(claimed, "date") and hasattr(actual, "date")):
        return False
    midnight = (actual.hour, actual.minute, actual.second, actual.microsecond) == (0, 0, 0, 0)
    return midnight and claimed.date() == actual.date()


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return a is not None and b is not None and abs(float(a) - float(b)) < 0.005
        except (TypeError, ValueError):
            return False
    if hasattr(a, "isoformat") or hasattr(b, "isoformat"):
        sa = a.isoformat() if hasattr(a, "isoformat") else str(a)
        sb = b.isoformat() if hasattr(b, "isoformat") else str(b)
        return sa.replace("+00:00", "") == sb.replace("+00:00", "")
    return a == b


def backfill_user_overrides(db: Session, user_id: str, dry_run: bool = False) -> dict:
    """
    Returns {"orders_touched": n, "fields": {field: count}}.

    Only fields that some claim actually asserts can be compared -- a field
    no source ever reports has nothing to differ FROM, so it is left alone
    rather than being mistaken for an edit.
    """
    orders = db.query(models.Order).filter_by(user_id=user_id).all()
    messages = (
        db.query(models.IngestedMessage)
        .filter(models.IngestedMessage.order_id.isnot(None))
        .all()
    )
    source_type = {s.id: s.type for s in db.query(models.Source).all()}

    by_order = defaultdict(list)
    for m in messages:
        by_order[m.order_id].append(m)

    touched = 0
    field_counts: dict[str, int] = defaultdict(int)

    for order in orders:
        msgs = by_order.get(order.id)
        if not msgs:
            # Nothing to resolve against, so nothing can be shown to be an
            # edit. Leave it entirely alone.
            continue

        resolved = _derived(
            claims.resolve(
                [
                    claims.build_claim(
                        m.payload, source_type.get(m.source_id), m.occurred_at
                    )
                    for m in msgs
                ]
            )
        )

        overrides = dict(order.user_overrides or {})
        changed = False
        for field, claimed in resolved.items():
            actual = getattr(order, field, None)
            if _same(claimed, actual):
                continue
            if _is_truncation(claimed, actual):
                continue
            # Store JSON-safe values: this column round-trips through the
            # JSON codec, and a datetime would not survive it.
            overrides[field] = actual.isoformat() if hasattr(actual, "isoformat") else actual
            field_counts[field] += 1
            changed = True

        if changed:
            touched += 1
            if not dry_run:
                order.user_overrides = overrides

    if not dry_run:
        db.commit()

    return {"orders_touched": touched, "fields": dict(field_counts)}
