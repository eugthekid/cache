"""
A unit's cost follows its order's price when a better price arrives (the
retailer's tax-inclusive email figure replacing the Discord pre-tax one),
but never overwrites a hand-typed cost or a sold unit's average costing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models, crud, schemas

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


engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()
user = models.User(email="local@inventory-tracker")
db.add(user)
db.commit()
discord = models.Source(user_id=user.id, type="discord_channel", name="chan")
email = models.Source(user_id=user.id, type="email_account", name="gmail")
db.add_all([discord, email])
db.commit()

crud.ingest_order(db, schemas.OrderCreate(
    source_id=discord.id, external_id="d1", status="success", quantity=3, unit_price=59.99,
    raw_product_text="Pokémon TCG: Elite Trainer Box", order_number="P1", site="pokemoncenter.com",
))
order = db.query(models.Order).filter_by(order_number="P1").one()
items = db.query(models.InventoryItem).filter_by(order_id=order.id).order_by(models.InventoryItem.unit_index).all()
check("starts at the Discord pre-tax price", [i.cost_basis for i in items], [59.99] * 3)

items[1].cost_basis = 50.00           # typed in by hand
items[2].status = "sold"              # a sale re-costs it at the product average
items[2].cost_basis = 61.25
db.commit()

crud.ingest_order(db, schemas.OrderCreate(
    source_id=email.id, external_id="<m1>:confirm:0", status="success", quantity=3, unit_price=65.31,
    raw_product_text="Pokémon TCG: Elite Trainer Box", order_number="P1", site="pokemoncenter.com",
))
db.refresh(order)
for i in items:
    db.refresh(i)
check("the order's price becomes the email's", round(order.unit_price, 2), 65.31)
check("an untouched unit follows it", round(items[0].cost_basis, 2), 65.31)
check("a hand-typed cost is left alone", items[1].cost_basis, 50.00)
check("a sold unit keeps its average costing", items[2].cost_basis, 61.25)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
