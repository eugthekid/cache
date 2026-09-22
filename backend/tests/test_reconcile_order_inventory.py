"""
Exercises crud.reconcile_order_inventory() and crud.item_status_for_shipping()
against a real in-memory SQLite DB -- proves units move
not_shipped -> in_transit -> in_hand automatically as an order's
shipping_status changes (2026-09-22), and that a unit the user has
independently sold/returned/lost is never touched by that automatic
sync, no matter what the order's shipping_status says.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models, crud

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
        user_id=user.id, source_id="src", external_id="ext-1", status="success",
        site="target.com", retailer="Target", shipping_status="not_shipped", quantity=2,
    )
    defaults.update(overrides)
    order = models.Order(**defaults)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


# --- item_status_for_shipping mapping ---
check("not_shipped -> not_shipped", crud.item_status_for_shipping("not_shipped"), "not_shipped")
check("label_created -> not_shipped", crud.item_status_for_shipping("label_created"), "not_shipped")
check("in_transit -> in_transit", crud.item_status_for_shipping("in_transit"), "in_transit")
check("delivered -> in_hand", crud.item_status_for_shipping("delivered"), "in_hand")
check("exception -> None (no mapping; callers must leave existing units alone)", crud.item_status_for_shipping("exception"), None)


# --- test 1: creating a success order creates units with the RIGHT initial status ---
db, user = make_db()
order = make_order(db, user, shipping_status="in_transit")
crud.reconcile_order_inventory(db, order)
db.commit()
items = db.query(models.InventoryItem).filter_by(order_id=order.id).all()
check("new order already in_transit: units created as in_transit, not hardcoded in_hand", [i.status for i in items], ["in_transit", "in_transit"])


# --- test 2: shipping_status progresses -> existing units follow ---
order.shipping_status = "delivered"
crud.reconcile_order_inventory(db, order)
db.commit()
items = db.query(models.InventoryItem).filter_by(order_id=order.id).filter(models.InventoryItem.deleted_at.is_(None)).all()
check("order delivered: existing units flip to in_hand", [i.status for i in items], ["in_hand", "in_hand"])


# --- test 3: a unit the user marked sold is NEVER touched by this sync ---
items[0].status = "sold"
items[0].sold_price = 40.0
db.commit()
order.shipping_status = "exception"  # simulate a later live-tracking exception
crud.reconcile_order_inventory(db, order)
db.commit()
db.refresh(items[0])
db.refresh(items[1])
check("sold unit stays sold even though the order's shipping_status changed", items[0].status, "sold")
check("the OTHER (still in_hand) unit is untouched -- 'exception' has no mapping, doesn't force a status", items[1].status, "in_hand")


# --- test 4: cancellation soft-deletes only the shippable units, restore brings the right status back ---
db2, user2 = make_db()
order2 = make_order(db2, user2, shipping_status="not_shipped")
crud.reconcile_order_inventory(db2, order2)
db2.commit()
items2 = db2.query(models.InventoryItem).filter_by(order_id=order2.id).all()
items2[0].status = "sold"  # one already sold before the cancellation email arrives
db2.commit()

order2.status = "cancelled"
crud.reconcile_order_inventory(db2, order2)
db2.commit()
live_after_cancel = db2.query(models.InventoryItem).filter_by(order_id=order2.id).filter(models.InventoryItem.deleted_at.is_(None)).all()
check("cancellation: the sold unit survives (still live)", len(live_after_cancel), 1)
check("cancellation: the survivor is the sold one, not the not_shipped one", live_after_cancel[0].status, "sold")

# Un-cancel, now with the order already in_transit -- restored unit should
# come back as in_transit, not stuck at whatever it was pre-cancellation.
order2.status = "success"
order2.shipping_status = "in_transit"
crud.reconcile_order_inventory(db2, order2)
db2.commit()
live_after_restore = db2.query(models.InventoryItem).filter_by(order_id=order2.id).filter(models.InventoryItem.deleted_at.is_(None)).all()
statuses_after_restore = sorted(i.status for i in live_after_restore)
check("un-cancel: 2 live units again (1 restored + 1 already-live sold one)", len(live_after_restore), 2)
check("un-cancel: the restored unit comes back as in_transit (the order's CURRENT shipping_status), not stale", statuses_after_restore, ["in_transit", "sold"])


# --- test 5: cost_basis backfills once the order's own price becomes
# known, even though the unit was created earlier with none (the real
# live shape: a Discord-only claim creates the unit with no price yet,
# a later email confirmation resolves order.unit_price) ---
db3, user3 = make_db()
order3 = make_order(db3, user3, shipping_status="not_shipped", unit_price=None)
crud.reconcile_order_inventory(db3, order3)
db3.commit()
items3 = db3.query(models.InventoryItem).filter_by(order_id=order3.id).all()
check("no order price yet: units created with cost_basis=None", [i.cost_basis for i in items3], [None, None])

# One unit gets sold before the price is ever known -- backfill must
# still reach it (profit calc needs a real cost_basis on a sold unit
# too), without touching its status.
items3[0].status = "sold"
items3[0].sold_price = 45.0
db3.commit()

order3.unit_price = 24.99
crud.reconcile_order_inventory(db3, order3)
db3.commit()
db3.refresh(items3[0])
db3.refresh(items3[1])
check("price arrives later: BOTH units backfilled, including the sold one", [items3[0].cost_basis, items3[1].cost_basis], [24.99, 24.99])
check("backfilling cost_basis never touches the sold unit's status", items3[0].status, "sold")

# An existing, real cost_basis must never be overwritten by a later
# (possibly different) order.unit_price -- purely additive, fills gaps
# only.
items3[1].cost_basis = 30.0
db3.commit()
order3.unit_price = 24.99
crud.reconcile_order_inventory(db3, order3)
db3.commit()
db3.refresh(items3[1])
check("an already-set cost_basis is never overwritten", items3[1].cost_basis, 30.0)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
