"""
Merging two products must not leave one purchase counted twice.

Real case (2026-10-22): Discord named the 30th Celebration tin "Pokémon 30th
Collection Tin Trading Cards (Styles May Vary)" and Target's email named it
"30th Celebration Tin (Sylveon or Greninja)- Styles May Vary". They resolved to
two products, so the same order number got a Discord row AND an email row.
After the products were merged, both rows and both rows' units stayed -- 4
phantom "order placed" tins.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud, models, products
from app.database import Base

passed = failed = 0


def check(label, got, want):
    global passed, failed
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        expected: {want!r}\n        got:      {got!r}")
    passed, failed = passed + ok, failed + (not ok)


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()
user = crud.get_or_create_default_user(db)
discord = models.Source(user_id=user.id, type="discord_channel", name="checkouts")
email = models.Source(user_id=user.id, type="email_account", name="gmail")
db.add_all([discord, email])
db.commit()

DISCORD_NAME = "Pokémon 30th Collection Tin Trading Cards (Styles May Vary)"
EMAIL_NAME = "Pokemon Trading Card Game: 30th Celebration Tin (Sylveon or Greninja)- Styles May Vary"
p_discord = products.resolve_product(db, user.id, DISCORD_NAME)
p_email = products.resolve_product(db, user.id, EMAIL_NAME)
db.commit()


def order(source, external, name, product, number, ship, qty=2, price=None):
    payload = {"source_id": source.id, "external_id": external, "status": "success", "raw_product_text": name,
               "quantity": qty, "unit_price": price, "order_number": number, "shipping_status": ship, "site": "target"}
    o = models.Order(user_id=user.id, source_id=source.id, external_id=external, status="success", raw_product_text=name,
                     quantity=qty, unit_price=price, order_number=number, shipping_status=ship, site="target",
                     product_id=product.id, purchased_at=datetime(2026, 8, 14))
    db.add(o)
    db.flush()
    db.add(models.IngestedMessage(user_id=user.id, source_id=source.id, external_id=external, order_id=o.id, payload=payload,
                                  occurred_at=datetime(2026, 8, 14)))
    db.commit()
    crud.reconcile_order_inventory(db, o)
    db.commit()
    return o


# One purchase seen by both sources, plus one purchase only Discord saw.
d1 = order(discord, "d1", DISCORD_NAME, p_discord, "902003599109668", "not_shipped", price=29.99)
e1 = order(email, "e1", EMAIL_NAME, p_email, "902003599109668", "delivered", price=32.65)
for item in db.query(models.InventoryItem).filter_by(order_id=e1.id):
    item.status = "sold"
db.commit()
d2 = order(discord, "d2", DISCORD_NAME, p_discord, "912003654265890", "not_shipped", price=29.99)
# Two lines of ONE cart from the same source are two purchases, never a duplicate.
c1 = order(discord, "c1", EMAIL_NAME, p_email, "P0035996055", "not_shipped", qty=1, price=15.99)
c2 = order(discord, "c2", EMAIL_NAME, p_email, "P0035996055", "not_shipped", qty=1, price=15.99)


def live_units(product_id):
    return [i for i, o in db.query(models.InventoryItem, models.Order).join(models.Order, models.InventoryItem.order_id == models.Order.id)
            .filter(models.Order.product_id == product_id, models.InventoryItem.deleted_at.is_(None))]


check("before: the purchase is counted twice", len(live_units(p_discord.id)) + len(live_units(p_email.id)), 2 + 2 + 2 + 1 + 1)

products.merge_products(db, user.id, source_id=p_discord.id, target_id=p_email.id)
db.expire_all()
rows = db.query(models.Order).filter_by(order_number="902003599109668").all()
check("the two rows of one purchase become one", len(rows), 1)
check("the row with progress is kept (its sold units stay)", (rows[0].id, sorted(i.status for i in live_units(p_email.id) if i.order_id == rows[0].id)),
      (e1.id, ["sold", "sold"]))
check("both messages now point at it, so a resync can't recreate the duplicate",
      sorted(m.external_id for m in db.query(models.IngestedMessage).filter_by(order_id=e1.id)), ["d1", "e1"])
check("it keeps the email's delivery status", rows[0].shipping_status, "delivered")
check("a purchase only one source saw is untouched", db.get(models.Order, d2.id) is not None, True)
check("two same-source lines of one cart are left alone", db.query(models.Order).filter_by(order_number="P0035996055").count(), 2)
check("after: units are the real count", len(live_units(p_email.id)), 2 + 2 + 1 + 1)

# A re-sent Discord message must not bring the duplicate back.
from app import schemas  # noqa: E402

again = crud.ingest_order(db, schemas.OrderCreate(source_id=discord.id, external_id="d1", status="success", raw_product_text=DISCORD_NAME,
                                                  quantity=2, unit_price=29.99, order_number="902003599109668", site="target"))
db.expire_all()
check("re-sending the Discord message doesn't recreate the row", db.query(models.Order).filter_by(order_number="902003599109668").count(), 1)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
