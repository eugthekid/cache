"""Editing an order's site by hand re-derives the store it shows under."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud, models, schemas
from app.database import Base

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()
user = crud.get_or_create_default_user(db)
source = models.Source(user_id=user.id, type="discord_channel", name="checkouts")
db.add(source)
db.commit()

order = crud.ingest_order(db, schemas.OrderCreate(source_id=source.id, external_id="m1", status="success",
                                                  raw_product_text="Prismatic Evolutions Elite Trainer Box", quantity=5))
assert order.retailer is None, order.retailer
crud.update_order(db, order, schemas.OrderUpdate(site="Walmart"))
ok = order.retailer == "Walmart"
print(f"  {'OK  ' if ok else 'FAIL'} typing the site in fills in the retailer (got {order.retailer!r})")
print(f"\n{int(ok)} passed, {int(not ok)} failed")
sys.exit(0 if ok else 1)
