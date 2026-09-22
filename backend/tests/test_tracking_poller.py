"""
Exercises tracking_poller._apply_update() directly against a real
in-memory SQLite DB and a fake provider (no network, no real 17TRACK
key needed) -- proves the two separate edge triggers this module owns:
sync_tracking_fields' existing delivered/exception alert, and the
NEW out-for-delivery/pickup alert keyed on tracking_detail actually
changing (not re-firing every cycle while the same status persists).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models, tracking_poller
from app.tracking import TrackingUpdate

passed = failed = 0


def check(label, got, want):
    global passed, failed
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        expected: {want!r}")
        print(f"        got:      {got!r}")
    if ok:
        passed += 1
    else:
        failed += 1


class FakeProvider:
    def __init__(self, update: TrackingUpdate):
        self._update = update
        self.calls = 0

    def fetch(self, tracking_number, carrier=None):
        self.calls += 1
        return self._update


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = models.User(email="local@inventory-tracker")
    db.add(user)
    db.commit()
    return db, user


def make_order(db, user, **overrides):
    defaults = dict(
        user_id=user.id,
        source_id="src",
        external_id=f"ext-{overrides.get('order_number', 'x')}",
        status="success",
        site="target.com",
        retailer="Target",
        shipping_status="in_transit",
        tracking_number="1Z999AA10123456784",
    )
    defaults.update(overrides)
    order = models.Order(**defaults)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


# --- test 1: a plain InTransit-shaped update doesn't touch alert fields ---
db, user = make_db()
order = make_order(db, user, order_number="1")
provider = FakeProvider(TrackingUpdate(shipping_status="in_transit", detail="In transit", alert=False))
tracking_poller._apply_update(db, provider, order)
check("plain in_transit update: no alert fired", order.shipping_alert_at, None)
check("plain in_transit update: shipping_status stays in_transit", order.shipping_status, "in_transit")
check("plain in_transit update: tracking_checked_at is set", order.tracking_checked_at is not None, True)


# --- test 2: delivered fires the EXISTING sync_tracking_fields alert ---
db2, user2 = make_db()
order2 = make_order(db2, user2, order_number="2")
provider2 = FakeProvider(TrackingUpdate(shipping_status="delivered", detail="Delivered", alert=False))
tracking_poller._apply_update(db2, provider2, order2)
check("delivered: shipping_status", order2.shipping_status, "delivered")
check("delivered: sync_tracking_fields' own edge trigger fires the alert", order2.shipping_alert_at is not None, True)


# --- test 3: OutForDelivery fires the NEW alert (shipping_status stays in_transit) ---
db3, user3 = make_db()
order3 = make_order(db3, user3, order_number="3")
provider3 = FakeProvider(TrackingUpdate(shipping_status="in_transit", detail="Out for delivery", alert=True))
tracking_poller._apply_update(db3, provider3, order3)
check("OutForDelivery: shipping_status stays in_transit (no new enum value)", order3.shipping_status, "in_transit")
check("OutForDelivery: the new detail-change alert fires", order3.shipping_alert_at is not None, True)
first_alert_at = order3.shipping_alert_at

# --- test 4: a SECOND cycle with the SAME detail must NOT re-alert ---
order3.shipping_alert_seen_at = order3.shipping_alert_at  # simulate the user having seen it
provider3b = FakeProvider(TrackingUpdate(shipping_status="in_transit", detail="Out for delivery", alert=True))
tracking_poller._apply_update(db3, provider3b, order3)
check("same detail, second cycle: alert timestamp unchanged (not re-fired)", order3.shipping_alert_at, first_alert_at)
check("same detail, second cycle: stays marked seen (not silently un-dismissed)", order3.shipping_alert_seen_at, first_alert_at)

# --- test 5: detail genuinely CHANGES (out for delivery -> delivered) -> re-alerts ---
provider3c = FakeProvider(TrackingUpdate(shipping_status="delivered", detail="Delivered", alert=False))
tracking_poller._apply_update(db3, provider3c, order3)
check("detail changes to Delivered: shipping_status updates", order3.shipping_status, "delivered")
check("detail changes to Delivered: alert fires again (sync_tracking_fields' own trigger)", order3.shipping_alert_at != first_alert_at, True)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
