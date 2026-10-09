"""
The product screen's HTTP routes end to end, against a throwaway in-memory
database: adding units for a store off the manual list, price validation,
and the 422 for a store that isn't allowed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app import models

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


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def override():
    db = Session()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override
db = Session()
from app import crud
user = crud.get_or_create_default_user(db)
product = models.Product(user_id=user.id, canonical_name="Booster Bundle", normalized_key="booster-bundle")
db.add(product)
db.commit()
order = models.Order(
    user_id=user.id, source_id="s", external_id="e", status="success", site="x", retailer="Target",
    quantity=2, unit_price=30.0, shipping_status="delivered", product_id=product.id, order_number="T1",
)
db.add(order)
db.commit()
crud.reconcile_order_inventory(db, order)
db.commit()
pid = product.id

client = TestClient(app)
dash = client.get(f"/products/{pid}/dashboard").json()
check("dashboard lists the addable stores", dash["addable_retailers"], ["Walmart", "Crunchyroll", "Best Buy", "Menards"])

res = client.put(f"/products/{pid}/counts", json={"retailers": [
    {"retailer": "Walmart", "order_placed": 0, "in_transit": 0, "in_hand_or_sold": 3, "unit_price": 28.5}]})
check("adding Walmart succeeds", res.status_code, 200)
body = res.json()
wm = next(r for r in body["retailers"] if r["retailer"] == "Walmart")
check("Walmart card: 3 in hand at the typed price", (wm["in_hand_or_sold"], wm["avg_unit_price"]), (3, 28.5))
check("Walmart left the addable list", "Walmart" in body["addable_retailers"], False)
check("totals include it", (body["in_hand"], body["total_units"]), (5, 5))

res = client.put(f"/products/{pid}/counts", json={"retailers": [
    {"retailer": "Costco", "order_placed": 0, "in_transit": 0, "in_hand_or_sold": 1}]})
check("a store off the list is a 422", res.status_code, 422)
res = client.put(f"/products/{pid}/counts", json={"retailers": [
    {"retailer": "Menards", "order_placed": 0, "in_transit": 0, "in_hand_or_sold": 1, "unit_price": -4}]})
check("a negative price is a 422", res.status_code, 422)
after = client.get(f"/products/{pid}/dashboard").json()
check("a refused edit changes nothing", (after["total_units"], "Menards" in [r["retailer"] for r in after["retailers"]]), (5, False))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
