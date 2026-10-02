"""
A bulk status change must be recorded as a user override, same as a
single-order edit, so a later message about the order can't revert it.
Found 2026-10-02 while cancelling an order from the grouped Orders view:
the bulk endpoint set the column directly, so the next claim re-resolved
the order back to 'success'.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models, crud, schemas
from app.routers.orders import bulk_update_order_status

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
    source_id=discord.id, external_id="d1", status="success", quantity=2, unit_price=59.99,
    raw_product_text="Pokémon TCG: Elite Trainer Box", order_number="P0001", site="pokemoncenter.com",
))
order = db.query(models.Order).filter_by(order_number="P0001").one()
units = lambda: db.query(models.InventoryItem).filter_by(order_id=order.id).filter(models.InventoryItem.deleted_at.is_(None)).count()
check("starts as a success order with 2 units", (order.status, units()), ("success", 2))

result = bulk_update_order_status(schemas.BulkOrderStatusUpdate(ids=[order.id], status="cancelled"), db)
db.refresh(order)
check("bulk cancel reports 1 updated", result.updated, 1)
check("bulk cancel: status is cancelled and its units are gone", (order.status, units()), ("cancelled", 0))
check("bulk cancel is recorded as a user override", (order.user_overrides or {}).get("status"), "cancelled")

# A later email about the same purchase must NOT bring it back.
crud.ingest_order(db, schemas.OrderCreate(
    source_id=email.id, external_id="<m1>:confirm:0", status="success", quantity=2, unit_price=65.31,
    raw_product_text="Pokémon TCG: Elite Trainer Box", order_number="P0001", site="pokemoncenter.com",
))
rows = db.query(models.Order).filter_by(order_number="P0001").all()
for r in rows:
    db.refresh(r)
check("a later confirmation email does not un-cancel it", sorted(r.status for r in rows), ["cancelled"])
check("and no units reappear", units(), 0)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
