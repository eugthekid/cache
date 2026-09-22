"""
tracking_poller.py
-------------------
Polls the configured live-tracking provider (see app/tracking.py) on a
timer and updates orders' shipping_status/estimated_delivery/detail from
it -- IN-PROCESS, as a background thread inside the backend, same shape
as app/email_poller.py and for the same reason: nothing here needs to
survive Cache being closed, a package sitting in transit is still there
next time Cache opens and polls it.

WHY 30 MINUTES, NOT EMAIL'S 2: a shipment's status changes on the order
of hours, not minutes -- polling as fast as email would burn through
17TRACK's rate limit (3 req/sec) and, for a provider with a different
quota model, could burn real quota for no benefit. 30 minutes is still
frequent enough to catch "out for delivery" and "delivered" the same
day they happen.

WHICH ORDERS GET POLLED, and why that set shrinks itself: only orders
with status='success' (a failed/cancelled order was never shipped),
a tracking_number (nothing to look up otherwise), and
shipping_status in ('label_created', 'in_transit') -- once a live check
resolves an order to 'delivered' or 'exception', later poll cycles never
touch it again. That's what keeps this affordable on 17TRACK's free
tier: the trackable set is "currently moving", not "everything ever
shipped".
"""

import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app import crud, models, tracking
from app.database import SessionLocal
from app.routers.tracking_account import _read_env

POLL_SECONDS = 1800

# Courtesy delay between individual orders within one cycle -- keeps this
# comfortably under 17TRACK's 3 req/sec limit even though a single
# fetch() can be 1-3 HTTP calls (see seventeen_track.py's register-on-
# demand flow), without hardcoding that provider's own rate limit here.
_BETWEEN_ORDERS_SECONDS = 0.5

_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event] = None


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def start() -> None:
    """Starts the poller if it isn't already running, using whatever
    credential is currently saved. A no-op if tracking isn't configured
    or the poller is already up -- safe to call unconditionally from
    startup and from routers/tracking_account.py after every save."""
    global _thread, _stop_event
    if is_running():
        return

    values = _read_env()
    api_key = values.get("TRACKING_API_KEY")
    if not api_key:
        return

    _stop_event = threading.Event()
    _thread = threading.Thread(
        target=_run_forever, args=(_stop_event, api_key), daemon=True, name="tracking-poller"
    )
    _thread.start()


def stop() -> None:
    """Signals the loop to stop and waits for the current cycle to
    finish -- called on backend shutdown and whenever Settings clears or
    changes the tracking credential."""
    global _thread, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=30)
    _thread = None
    _stop_event = None


def restart() -> None:
    """Called after Settings saves a changed API key -- the running
    thread captured the OLD key as a plain argument, so there's nothing
    to hot-swap; stop and start fresh instead."""
    stop()
    start()


def _run_forever(stop_event: threading.Event, api_key: str) -> None:
    print(f"[tracking] watching shipments via 17TRACK, polling every {POLL_SECONDS}s.")
    while not stop_event.is_set():
        try:
            _run_once(api_key, stop_event)
        except Exception as exc:  # never let one bad cycle end the loop
            print(f"[tracking] poll failed: {exc!r} -- will retry next cycle", file=sys.stderr)
        stop_event.wait(POLL_SECONDS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_once(api_key: str, stop_event: threading.Event) -> None:
    """
    One poll cycle. EACH ORDER COMMITS ON ITS OWN, right after it's
    updated -- not batched into one commit at the end. Found live in
    app/email_poller.py earlier this same project (see that module's own
    docstring): a single end-of-cycle commit means one order's update
    failure can roll back every earlier order this cycle already
    resolved. Applying that lesson here from the start rather than
    re-discovering it.
    """
    provider = tracking.resolve_provider(api_key)
    if provider is None:
        return

    db: Session = SessionLocal()
    try:
        orders = (
            crud.live_orders(db)
            .filter(models.Order.status == "success")
            .filter(models.Order.tracking_number.isnot(None))
            .filter(models.Order.shipping_status.in_(["label_created", "in_transit"]))
            .all()
        )
        if not orders:
            return

        checked = failed = 0
        for order in orders:
            if stop_event.is_set():
                break
            try:
                _apply_update(db, provider, order)
                db.commit()
                checked += 1
            except Exception as exc:
                print(f"[tracking] update failed for order {order.id}: {exc!r}", file=sys.stderr)
                db.rollback()
                failed += 1
            time.sleep(_BETWEEN_ORDERS_SECONDS)

        print(f"[tracking] checked {checked} shipment(s), {failed} failed.")
    finally:
        db.close()


def _apply_update(db: Session, provider: tracking.TrackingProvider, order: models.Order) -> None:
    previous_shipping_status = order.shipping_status
    previous_detail = order.tracking_detail
    # Captured before sync_tracking_fields runs, so an alert THIS
    # function set on an earlier cycle can be restored if that call
    # clears it for a reason that doesn't apply here -- see below.
    previous_alert_at = order.shipping_alert_at
    previous_alert_seen_at = order.shipping_alert_seen_at

    update = provider.fetch(order.tracking_number, order.carrier)
    order.tracking_checked_at = _now()

    if update.shipping_status:
        order.shipping_status = update.shipping_status
    if update.detail:
        order.tracking_detail = update.detail
    if update.estimated_delivery:
        order.estimated_delivery = update.estimated_delivery
    if update.carrier and not order.carrier:
        order.carrier = update.carrier

    # Owns the 'delivered'/'exception' edge trigger -- unchanged, generic,
    # works the same whether shipping_status came from email or here.
    crud.sync_tracking_fields(order, previous_shipping_status)

    # Keeps this order's inventory units' own status in step with the
    # shipping_status a live check just updated -- the SAME function the
    # email-driven path already calls after every resolve (see
    # app/crud.py's reconcile_order_inventory), so a unit transitions
    # not_shipped -> in_transit -> in_hand exactly the same way regardless
    # of whether the update came from an email or from here.
    crud.reconcile_order_inventory(db, order)

    # A second, provider-specific edge trigger this module owns: "out for
    # delivery" and "available for pickup" don't move shipping_status
    # (see seventeen_track.py's _STATUS_MAP), so sync_tracking_fields
    # above never sees or protects them -- worse, ITS OWN "not in
    # {delivered, exception} -> clear the alert" branch just unconditionally
    # wiped shipping_alert_at above, since shipping_status is still
    # 'in_transit' from its point of view. Found live by this file's own
    # test (test_tracking_poller.py): a same-detail second cycle silently
    # un-alerted an already-real, already-seen notification. Fixed by
    # only ever setting a FRESH alert when tracking_detail genuinely
    # changed (a new alert-worthy moment), and otherwise restoring
    # whatever alert state existed before sync_tracking_fields ran --
    # never re-alerting on a persisting status, never silently dropping
    # one either.
    if update.alert:
        if order.tracking_detail != previous_detail:
            order.shipping_alert_at = _now()
            order.shipping_alert_seen_at = None
        elif order.shipping_status not in {"delivered", "exception"}:
            order.shipping_alert_at = previous_alert_at
            order.shipping_alert_seen_at = previous_alert_seen_at
