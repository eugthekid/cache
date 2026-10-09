"""
The per-product screen: breakdown by retailer and stage, hand-edited counts
that the automatic pipeline must not undo, and sales costed at the average.

The fixture mirrors the real case that prompted it (2026-10-06): Pokemon
Center shows 6 order-placed + 66 in-transit units for the 30th Celebration
Booster Bundle, but the user knows they hold 69, all in hand (some orders
were cancelled, and PC delivery isn't tracked by email), while Target has
10 / 22 / 18.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models, crud, product_dashboard as pd

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


def raises(label, fn):
    try:
        fn()
    except ValueError:
        check(label, True, True)
        return
    check(label, "no error", "ValueError")


def build():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = models.User(email="local@inventory-tracker")
    db.add(user)
    db.commit()
    product = models.Product(user_id=user.id, canonical_name="Booster Bundle", normalized_key="booster-bundle")
    db.add(product)
    db.commit()
    orders = {}
    spec = [
        ("pc-placed", "Pokémon Center", 6, "not_shipped", 26.94),
        ("pc-a", "Pokémon Center", 30, "in_transit", 26.94),
        ("pc-b", "Pokémon Center", 36, "in_transit", 26.94),
        ("tg-placed", "Target", 10, "not_shipped", 34.83),
        ("tg-transit", "Target", 22, "in_transit", 32.25),
        ("tg-hand", "Target", 18, "delivered", 33.88),
    ]
    for key, retailer, qty, ship, price in spec:
        order = models.Order(
            user_id=user.id, source_id="src", external_id=key, status="success", site="x",
            retailer=retailer, quantity=qty, unit_price=price, shipping_status=ship,
            product_id=product.id, order_number=key, purchased_at=datetime(2026, 9, 1),
        )
        db.add(order)
        db.commit()
        crud.reconcile_order_inventory(db, order)
        db.commit()
        orders[key] = order
    return db, user, product, orders


def retailer(dash, name):
    return next(r for r in dash["retailers"] if r["retailer"] == name)


def triple(r):
    return (r["order_placed"], r["in_transit"], r["in_hand_or_sold"])


# --- the breakdown ---------------------------------------------------------
db, user, product, orders = build()
dash = pd.build_dashboard(db, user.id, product)
check("PC stage counts", triple(retailer(dash, "Pokémon Center")), (6, 66, 0))
check("Target stage counts", triple(retailer(dash, "Target")), (10, 22, 18))
check("totals", (dash["order_placed"], dash["in_transit"], dash["in_hand"], dash["sold"], dash["total_units"]), (16, 88, 18, 0, 122))
check("PC unit price", round(retailer(dash, "Pokémon Center")["avg_unit_price"], 2), 26.94)
tg = retailer(dash, "Target")
check("Target price range", (round(tg["min_unit_price"], 2), round(tg["max_unit_price"], 2)), (32.25, 34.83))

# --- editing counts: PC 6 / 66 / 0  ->  0 / 0 / 69 --------------------------
pd.apply_counts(db, user.id, product, [{"retailer": "Pokémon Center", "order_placed": 0, "in_transit": 0, "in_hand_or_sold": 69}])
db.commit()
dash = pd.build_dashboard(db, user.id, product)
check("PC edited to 0 / 0 / 69", triple(retailer(dash, "Pokémon Center")), (0, 0, 69))
check("Target untouched by a PC edit", triple(retailer(dash, "Target")), (10, 22, 18))
check("top totals follow the edit", (dash["order_placed"], dash["in_transit"], dash["in_hand"], dash["total_units"]), (10, 22, 87, 119))

# --- the automatic pipeline must not undo it -------------------------------
for key in ("pc-placed", "pc-a", "pc-b"):
    order = orders[key]
    order.shipping_status = "in_transit"  # e.g. a tracking update arriving
    crud.reconcile_order_inventory(db, order)
db.commit()
dash = pd.build_dashboard(db, user.id, product)
check("a later shipping update leaves hand-set PC units alone", triple(retailer(dash, "Pokémon Center")), (0, 0, 69))
check("the 3 removed units are not restored by the next sync", retailer(dash, "Pokémon Center")["units"], 69)

# a retailer cancelling the order after the edit doesn't wipe what you said you hold
orders["pc-a"].status = "cancelled"
crud.reconcile_order_inventory(db, orders["pc-a"])
db.commit()
dash = pd.build_dashboard(db, user.id, product)
check("a later cancellation doesn't remove units you set by hand", retailer(dash, "Pokémon Center")["units"], 69)
orders["pc-a"].status = "success"
crud.reconcile_order_inventory(db, orders["pc-a"])
db.commit()

# --- increasing a count creates units at the retailer's price --------------
pd.apply_counts(db, user.id, product, [{"retailer": "Pokémon Center", "order_placed": 0, "in_transit": 2, "in_hand_or_sold": 69}])
db.commit()
dash = pd.build_dashboard(db, user.id, product)
pc = retailer(dash, "Pokémon Center")
check("added units land in the stage asked for", (triple(pc), pc["units"]), ((0, 2, 69), 71))
check("added units carry the retailer's price", round(pc["avg_unit_price"], 2), 26.94)
pd.apply_counts(db, user.id, product, [{"retailer": "Pokémon Center", "order_placed": 0, "in_transit": 0, "in_hand_or_sold": 69}])
db.commit()
check("and can be taken away again", triple(retailer(pd.build_dashboard(db, user.id, product), "Pokémon Center")), (0, 0, 69))

# --- bad input -------------------------------------------------------------
raises("negative counts are refused", lambda: pd.apply_counts(db, user.id, product, [{"retailer": "Target", "order_placed": -1, "in_transit": 0, "in_hand_or_sold": 0}]))

# --- sales, costed at the average ------------------------------------------
dash = pd.build_dashboard(db, user.id, product)
avg = dash["avg_cost"]
check("average cost is invested / units", round(avg, 4), round(dash["invested"] / dash["total_units"], 4))

sale = pd.record_sale(db, user.id, product, 4, 45.0, "eBay", None)
db.commit()
dash = pd.build_dashboard(db, user.id, product)
check("a sale moves units from in hand to sold", (dash["in_hand"], dash["sold"], dash["total_units"]), (83, 4, 119))
check("sale is costed at the average", round(dash["sales"][0]["unit_cost"], 4), round(avg, 4))
check("sale profit = (price - average cost) x quantity", round(dash["sales"][0]["profit"], 2), round((45.0 - avg) * 4, 2))
check("retailer 'in hand / sold' is unchanged by a sale", (triple(retailer(dash, "Pokémon Center")), triple(retailer(dash, "Target"))), ((0, 0, 69), (10, 22, 18)))
check("average cost is stable after a sale (sold units keep their real purchase price)", round(dash["avg_cost"], 4), round(avg, 4))

raises("can't sell more than is in hand", lambda: pd.record_sale(db, user.id, product, 84, 45.0, None, None))
raises("quantity must be positive", lambda: pd.record_sale(db, user.id, product, 0, 45.0, None, None))
raises("can't set in hand / sold below what's sold", lambda: pd.apply_counts(db, user.id, product, [{"retailer": "Target", "order_placed": 10, "in_transit": 22, "in_hand_or_sold": 0}] + [{"retailer": "Pokémon Center", "order_placed": 0, "in_transit": 0, "in_hand_or_sold": 0}]))
db.rollback()

# --- undoing a sale --------------------------------------------------------
sold_ids = list(sale.item_costs.keys())
pd.undo_sale(db, sale)
db.commit()
dash = pd.build_dashboard(db, user.id, product)
check("undo puts the units back in hand", (dash["in_hand"], dash["sold"]), (87, 0))
check("undo removes the sale from the list", dash["sales"], [])
restored = db.query(models.InventoryItem).filter(models.InventoryItem.id.in_(sold_ids)).all()
check("undo restores each unit's own cost", all(i.cost_basis in (26.94, 32.25, 33.88, 34.83) for i in restored), True)
check("undo clears the sale fields", all(i.sold_price is None and i.sold_at is None for i in restored), True)

# --- adding a store Cache has no orders for --------------------------------
db, user, product, orders = build()
dash = pd.build_dashboard(db, user.id, product)
check("addable retailers: the fixed list, none present yet", dash["addable_retailers"], ["Walmart", "Crunchyroll", "Best Buy", "Menards"])

pd.apply_counts(db, user.id, product, [{"retailer": "Walmart", "order_placed": 0, "in_transit": 1, "in_hand_or_sold": 4, "unit_price": 31.50}])
db.commit()
dash = pd.build_dashboard(db, user.id, product)
wm = retailer(dash, "Walmart")
check("Walmart gets a card with the counts typed", (triple(wm), wm["units"]), ((0, 1, 4), 5))
check("Walmart's unit price is the one typed", round(wm["avg_unit_price"], 2), 31.50)
check("top totals include the new store", (dash["in_transit"], dash["in_hand"], dash["total_units"]), (89, 22, 127))
check("Walmart is no longer addable, the rest still are", dash["addable_retailers"], ["Crunchyroll", "Best Buy", "Menards"])
standalone = db.query(models.InventoryItem).filter_by(retailer="Walmart").all()
check("those units stand alone, tagged with the retailer", (len(standalone), {i.order_id for i in standalone}, all(i.manual for i in standalone)), (5, {None}, True))

pd.apply_counts(db, user.id, product, [{"retailer": "Walmart", "order_placed": 0, "in_transit": 1, "in_hand_or_sold": 6}])
db.commit()
wm = retailer(pd.build_dashboard(db, user.id, product), "Walmart")
check("raising Walmart later reuses its price (no price typed)", (triple(wm), round(wm["avg_unit_price"], 2)), ((0, 1, 6), 31.50))
raises("a store off the list is refused", lambda: pd.apply_counts(db, user.id, product, [{"retailer": "Costco", "order_placed": 0, "in_transit": 0, "in_hand_or_sold": 3}]))
db.rollback()

sale = pd.record_sale(db, user.id, product, 2, 50.0, None, None)
db.commit()
check("units from a manual store can be sold", pd.build_dashboard(db, user.id, product)["sold"], 2)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
