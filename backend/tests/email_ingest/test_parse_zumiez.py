"""
Zumiez order emails, end to end. Fixtures are the user's REAL emails for
orders #35000118411 / #35000119158 (Oct 2026), captured through
imap_client.fetch_plaintext_body() -- exactly what the poller sees, including
the confirmation's HTML-only pipe-table rendering. Phone number, a third-party
address in Zumiez's footer, and link URLs are redacted; nothing else changed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud, models, schemas
from app.database import Base
from app.email_ingest import parse_zumiez as z
from app.email_ingest.classify import EmailKind, Retailer, classify
from app.email_ingest.ingest import build_claims, parse_email_date

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "zumiez"
passed = failed = 0


def check(label, got, want):
    global passed, failed
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        expected: {want!r}\n        got:      {got!r}")
    passed, failed = passed + ok, failed + (not ok)


def load(name):
    head, body = (FIXTURES / f"{name}.txt").read_text().split("\n---\n", 1)
    h = dict(line.split(": ", 1) for line in head.splitlines())
    return h["SUBJECT"], body, h["MSGID"], parse_email_date(h["DATE"])


# --- subjects ------------------------------------------------------------------
for subject, kind, number in [
    ("We have received your order #35000118411", EmailKind.CONFIRMATION, "35000118411"),
    ("We've shipped a package to you!", EmailKind.SHIPPED, None),
    ("We’ve shipped a package to you!", EmailKind.SHIPPED, None),
    ("A package for order #35000118411 is out for delivery", EmailKind.SHIPPED, "35000118411"),
    ("A package for order #35000118411 has been delivered", EmailKind.ARRIVED, "35000118411"),
]:
    c = classify(subject)
    check(f"classify: {subject[:45]}", (c.retailer, c.kind, c.order_number), (Retailer.ZUMIEZ, kind, number))
check("the order-number-less cancellation is left alone",
      classify("OH NO! YOUR RECENT ZUMIEZ ORDER HAS BEEN CANCELLED").kind, EmailKind.UNRECOGNIZED)

# --- confirmation (HTML-only, every item row printed three times) ---------------
subject, body, msgid, at = load("confirmation_35000118411")
lines = z.parse_confirmation(body)
check("one item despite the row being printed three times", len(lines), 1)
check("item: name with size as a dashed variant, qty, SKU",
      (lines[0].raw_product_text, lines[0].quantity, lines[0].external_sku),
      ("Santa Cruz x Pokémon TCG Blind Bag Skateboard Deck - Size 8.0", 1, "41298006980102"))
check("unit cost includes tax: $139.95 scaled to the $152.37 grand total", lines[0].unit_price, 152.37)
check("placed on", z.parse_purchased_at(body), "2026-10-17T17:02:43")
check("ship-to address", z.parse_ship_to_address(body), "Test Buyer, 123 Example Street, Springfield, New York, 00000")

# --- shipped (no tracking) / out for delivery / delivered ------------------------
_, shipped_body, _, _ = load("shipped_35000118411")
check("shipped: order number from the body", z.parse_order_number(shipped_body), "35000118411")
check("shipped: item SKU matches the confirmation's (prefix dropped)", [l.external_sku for l in z.parse_shipped_lines(shipped_body)], ["41298006980102"])
_, ofd_body, _, _ = load("out_for_delivery_35000118411")
check("out for delivery: tracking and ETA", (z.parse_tracking_number(ofd_body), z.parse_eta(ofd_body)), ("878861448075", "Friday, October 23"))

claims = build_claims(*load("delivered_35000118411"))
check("delivered: one claim, delivered, dated from the email",
      [(c.order_number, c.shipping_status, c.tracking_number, c.tracking_detail) for c in claims],
      [("35000118411", "delivered", "878861448075", "Delivered October 23, 2026")])
check("a generic 'shipped' subject from another store claims nothing",
      build_claims("We've shipped a package to you!", "Your Order # 12345678 shipped. Qty: 1", "<x@y>", None), [])

# --- all four emails for one order become ONE delivered order --------------------
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()
user = crud.get_or_create_default_user(db)
source = models.Source(user_id=user.id, type="email_account", name="gmail")
db.add(source)
db.commit()
for name in ["confirmation_35000118411", "shipped_35000118411", "out_for_delivery_35000118411", "delivered_35000118411"]:
    for claim in build_claims(*load(name)):
        crud.ingest_order(db, schemas.OrderCreate(**claim.to_payload(), source_id=source.id))
        db.commit()
orders = db.query(models.Order).all()
check("four emails, one order", len(orders), 1)
o = orders[0]
check("order: Zumiez, delivered, tracked by FedEx, tax-inclusive price",
      (o.retailer, o.order_number, o.shipping_status, o.tracking_number, o.carrier, o.unit_price),
      ("Zumiez", "35000118411", "delivered", "878861448075", "fedex", 152.37))
units = db.query(models.InventoryItem).filter_by(order_id=o.id).all()
check("one unit, in hand, at the tax-inclusive cost", [(u.status, u.cost_basis) for u in units], [("in_hand", 152.37)])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
