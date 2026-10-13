"""
The Dashboard's numbers: profit for this week / this month / all time, the
chart buckets, breakdowns by category, channel and product, unsold inventory
at cost, spend by retailer, and the sales-channel spelling guard.

Dates are pinned (today = Saturday 2026-10-10) so "this week" is the week of
Monday 2026-10-05 and "this month" is October.
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app import dashboard_overview as do
from app import product_dashboard as pd

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


TODAY = date(2026, 10, 10)
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()
user = models.User(email="local@inventory-tracker")
db.add(user)
db.commit()
etb = models.Product(user_id=user.id, canonical_name="Elite Trainer Box", normalized_key="etb", category="Pokémon TCG")
shoe = models.Product(user_id=user.id, canonical_name="Sneaker", normalized_key="sneaker", category="Sneakers / Clothing")
db.add_all([etb, shoe])
db.commit()


def order(product, retailer, price, bought):
    o = models.Order(user_id=user.id, source_id="s", external_id=f"{retailer}{bought}", status="success", site="x",
                     retailer=retailer, quantity=1, unit_price=price, product_id=product.id, shipping_status="delivered",
                     purchased_at=bought)
    db.add(o)
    db.commit()
    return o


def unit(o, status, cost, sold_price=None, sold_at=None, platform=None, product=None, created=None):
    i = models.InventoryItem(user_id=user.id, created_at=created or datetime(2026, 9, 1), order_id=o.id if o else None, status=status, cost_basis=cost,
                             sold_price=sold_price, sold_at=sold_at, sold_platform=platform,
                             product_id=product.id if (product and not o) else None)
    db.add(i)
    db.commit()
    return i


o_etb = order(etb, "Target", 100.0, datetime(2026, 9, 2))
o_shoe = order(shoe, "Kith", 50.0, datetime(2026, 8, 20))
o_new = order(etb, "Pokémon Center", 60.0, datetime(2026, 10, 6))
unit(o_etb, "sold", 100.0, 150.0, datetime(2026, 10, 6, 14), "Hunter Grey")   # this week, profit 50
unit(o_etb, "sold", 100.0, 140.0, datetime(2026, 10, 1, 10), "TCGPlayer")      # this month, last week, profit 40
unit(o_etb, "sold", 100.0, 130.0, datetime(2026, 9, 20, 10), "Hunter Grey")    # September, profit 30
unit(o_shoe, "sold", 50.0, 90.0, datetime(2026, 8, 25, 10), "eBay")            # August, profit 40
unit(o_new, "in_hand", 60.0)
unit(o_new, "in_transit", 60.0)
unit(None, "in_hand", 20.0, product=etb, created=datetime(2026, 9, 1))           # added by hand, no order

weekly = do.build_overview(db, user.id, "weekly", TODAY)
monthly = do.build_overview(db, user.id, "monthly", TODAY)
allt = do.build_overview(db, user.id, "all", TODAY)

check("all time: profit, revenue, units", (allt["kpis"]["profit"], allt["kpis"]["revenue"], allt["kpis"]["units_sold"]), (160.0, 510.0, 4))
check("all time: ROI is profit over cost", round(allt["kpis"]["roi"], 4), round(160 / 350, 4))
check("all time: margin is profit over revenue", round(allt["kpis"]["margin"], 4), round(160 / 510, 4))
check("monthly = October only", (monthly["kpis"]["profit"], monthly["kpis"]["units_sold"]), (90.0, 2))
check("weekly = the week of Oct 5 only", (weekly["kpis"]["profit"], weekly["kpis"]["revenue"], weekly["kpis"]["units_sold"]), (50.0, 150.0, 1))
check("weekly spent = purchases ordered this week", weekly["kpis"]["spent"], 120.0)
check("all time spent = everything bought", allt["kpis"]["spent"], 100 * 3 + 50 + 120 + 20 - 0.0)

wk = weekly["chart"]
check("weekly chart: 8 weeks, ending this one", (wk["granularity"], len(wk["buckets"]), wk["buckets"][-1]["key"], wk["buckets"][-1]["label"]), ("week", 8, "2026-10-05", "Oct 5"))
check("weekly chart: this week is marked in progress", [b["partial"] for b in wk["buckets"]], [False] * 7 + [True])
check("weekly chart: last week's sale lands in the week of Sep 28", next(b for b in wk["buckets"] if b["key"] == "2026-09-28")["profit"], 40.0)
mo = monthly["chart"]
check("monthly chart: 7 months ending October", (len(mo["buckets"]), mo["buckets"][0]["key"], mo["buckets"][-1]["key"]), (7, "2026-04", "2026-10"))
check("monthly chart: profit by sale month", [round(b["profit"]) for b in mo["buckets"]][-3:], [40, 30, 90])
check("monthly chart: spend by the month it was ordered", [round(b["spent"]) for b in mo["buckets"]][-4:], [0, 50, 320, 120])
check("all time chart starts at the first activity (August)", (allt["chart"]["buckets"][0]["key"], len(allt["chart"]["buckets"])), ("2026-08", 3))

cats = {r["name"]: r for r in allt["breakdown"]["category"]}
check("breakdown by category", (cats["Pokémon TCG"]["profit"], cats["Pokémon TCG"]["units"], cats["Sneakers / Clothing"]["profit"]), (120.0, 3, 40.0))
chans = {r["name"]: r["profit"] for r in allt["breakdown"]["channel"]}
check("breakdown by channel", chans, {"Hunter Grey": 80.0, "TCGPlayer": 40.0, "eBay": 40.0})
check("breakdown is sorted by profit, best first", [r["name"] for r in allt["breakdown"]["channel"]][0], "Hunter Grey")
check("breakdown follows the period", [r["name"] for r in weekly["breakdown"]["channel"]], ["Hunter Grey"])
check("breakdown by product", {r["name"]: r["units"] for r in allt["breakdown"]["product"]}, {"Elite Trainer Box": 3, "Sneaker": 1})

inv = allt["inventory"]
check("unsold inventory: units and cost", (inv["units"], inv["cost"]), (3, 140.0))
check("unsold inventory by stage", {s["stage"]: (s["units"], s["cost"]) for s in inv["stages"]}, {"in_hand": (2, 80.0), "in_transit": (1, 60.0), "not_shipped": (0, 0.0)})
spend = {r["name"]: r["spent"] for r in allt["spend_by_retailer"]}
check("spend by retailer, with hand-added units on their own line", spend, {"Target": 300.0, "Kith": 50.0, "Pokémon Center": 120.0, "Added by hand": 20.0})

empty = do.build_overview(db, "someone-with-no-data", "all", TODAY)
check("a user with no data gets zeros, not errors", (empty["kpis"]["profit"], empty["kpis"]["roi"], empty["inventory"]["units"]), (0, None, 0))

# --- the sale form's channel spelling guard ---------------------------------
check("known channels, most used first", pd.known_channels(db, user.id)[:2], ["Hunter Grey", "TCGPlayer"])
check("typing 'ebay' reuses the existing 'eBay'", pd.canonical_channel(db, user.id, "  ebay "), "eBay")
check("a brand new channel is kept as typed", pd.canonical_channel(db, user.id, "Local Shop"), "Local Shop")
check("blank means no channel", pd.canonical_channel(db, user.id, "   "), None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
