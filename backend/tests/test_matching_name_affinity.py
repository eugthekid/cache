"""
Proves matching rule 6 (name affinity) stops one purchase splitting into a
row per event when the retailer's confirmation title and its shipping
title differ -- the recurring duplicate-order bug. Each scenario replays
the real shapes found in the live database ("Scarlet Violet Elite Trainer
Box" vs "Scarlet & Violet--Prismatic Evolutions Elite Trainer Box", the
30th Celebration "Styles May Vary" boxes) through crud.ingest_order, the
same entry point the email poller and Discord bot use.

The guard cases matter as much as the fix: a wrong merge destroys a unit,
so every ambiguity must leave the claim unmatched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models, crud, schemas, matching

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
    email = models.Source(user_id=user.id, type="email_account", name="gmail")
    discord = models.Source(user_id=user.id, type="discord_channel", name="chan")
    discord2 = models.Source(user_id=user.id, type="discord_channel", name="chan2")
    db.add_all([email, discord, discord2])
    db.commit()
    return db, email, discord, discord2


def send(db, source, ext, text, qty, price=None, order_number="912003426943112", **kw):
    payload = dict(
        source_id=source.id, external_id=ext, status="success", raw_product_text=text,
        quantity=qty, unit_price=price, order_number=order_number, site="target.com",
    )
    payload.update(kw)
    crud.ingest_order(db, schemas.OrderCreate(**payload))


def rows(db, order_number="912003426943112"):
    return db.query(models.Order).filter_by(order_number=order_number).all()


# --- pure helpers ---
check("tokens drop boilerplate and bare numbers",
      sorted(matching.name_tokens("Pokémon 30th Anniversary EX Box 2")), ["30th", "anniversary", "box", "ex"])
check("affinity: Scarlet Violet ETB vs Prismatic Evolutions ETB",
      matching.name_affinity("Pokémon Scarlet Violet Elite Trainer Box",
                             "Pokémon Trading Card Game: Scarlet & Violet—Prismatic Evolutions Elite Trainer Box")[0] >= 2, True)
check("affinity: unrelated products share nothing",
      matching.name_affinity("Pokémon Poster Collection", "Squishmallows Plush 8 inch")[0], 0)
check("email confirm claim kind", matching.claim_kind("<a@b>:confirm", "email_account"), "confirm")
check("email line ship claim kind", matching.claim_kind("<a@b>:ship:2", "email_account"), "ship")
check("email arrived has no kind", matching.claim_kind("<a@b>:arrived", "email_account"), None)
check("discord counts as confirm", matching.claim_kind("123456", "discord_channel"), "confirm")


# --- the live bug: confirm (marketing title) then ship (specific title) then arrived ---
db, email, discord, _ = make_db()
send(db, email, "<m1>:confirm", "Pokémon Scarlet Violet Elite Trainer Box", 2, 76.2)
send(db, email, "<m2>:ship", "Pokémon Trading Card Game: Scarlet & Violet—Prismatic Evolutions Elite Trainer Box", 2,
     shipping_status="in_transit", tracking_number="1Z999")
send(db, email, "<m3>:arrived", None, None, shipping_status="delivered")
r = rows(db)
check("confirm + ship + arrived = ONE order", len(r), 1)
check("that order is delivered", r[0].shipping_status, "delivered")
check("it carries the specific (ship) name", "Prismatic" in (r[0].raw_product_text or ""), True)
check("it kept the confirmation price", r[0].unit_price, 76.2)
live = db.query(models.InventoryItem).filter_by(order_id=r[0].id).filter(models.InventoryItem.deleted_at.is_(None)).count()
check("exactly 2 inventory units, not 4", live, 2)


# --- same purchase arriving out of order: ship first, confirm later ---
db, email, discord, _ = make_db()
send(db, email, "<m2>:ship", "Pokémon Trading Card Game: Scarlet & Violet—Prismatic Evolutions Elite Trainer Box", 2)
send(db, email, "<m1>:confirm", "Pokémon Scarlet Violet Elite Trainer Box", 2, 76.2)
check("ship then confirm = ONE order", len(rows(db)), 1)


# --- Discord generic title + later email ship with the specific one ---
db, email, discord, _ = make_db()
send(db, discord, "1001", "Pokémon 30th Anniversary EX Box 2", 2, 29.99)
send(db, email, "<m2>:ship", "Pokémon Trading Card Game: 30th Celebration Greninja ex Box", 2)
check("discord generic + email ship = ONE order", len(rows(db)), 1)


# --- guards: must NOT merge ---
db, email, discord, _ = make_db()
send(db, email, "<m1>:confirm", "Pokémon Scarlet Violet Elite Trainer Box", 2, 76.2)
send(db, email, "<m2>:ship", "Pokémon Trading Card Game: Scarlet & Violet—Prismatic Evolutions Elite Trainer Box", 1)
check("quantity disagreement stays separate", len(rows(db)), 2)

db, email, discord, _ = make_db()
send(db, email, "<m1>:confirm", "Pokémon Scarlet Violet Elite Trainer Box", 1, 76.2)
send(db, email, "<m2>:ship", "Pokémon Trading Card Game: Scarlet & Violet—Prismatic Evolutions Elite Trainer Box", 1)
send(db, email, "<m3>:ship", "Pokémon Trading Card Game: Scarlet & Violet—Journey Together Elite Trainer Box", 1)
check("a line already shipped is not adopted by a second, different ship", len(rows(db)), 2)

db, email, discord, discord2 = make_db()
send(db, discord, "2001", "Pokémon 30th Anniversary Poster Collection", 1, 21.99)
send(db, discord, "2002", "Pokémon 30th Anniversary Poster Collection Deluxe", 1, 21.99)
check("two lines from one discord source are never folded together", len(rows(db)), 2)

db, email, discord, discord2 = make_db()
send(db, discord, "3001", "Pokémon 30th Celebration Poster Collection Set A", 1, 21.99)
send(db, discord2, "3002", "Pokémon 30th Celebration Poster Collection Set B", 1, 23.49)
# Two equally plausible lines from different channels: the email cannot say
# which it is, so it must not guess.
before = len(rows(db))
send(db, email, "<m1>:ship", "Pokémon Trading Card Game: 30th Celebration Poster Collection", 1)
check("a tie between equally plausible lines leaves the claim unmatched", (before, len(rows(db))), (2, 3))

db, email, discord, discord2 = make_db()
send(db, discord, "4001", "Pokémon 30th Celebration Tech Sticker Collection (Styles May Vary)", 1, 14.99)
send(db, discord2, "4002", "Pokémon 30th Anniversary Poster Collection", 1, 21.99)
send(db, email, "<m1>:ship", "Pokémon Trading Card Game: 30th Celebration Tech Sticker Collection (Lucario)", 1)
check("best-scoring line wins over a weak partial-word overlap", len(rows(db)), 2)

db, email, discord, _ = make_db()
send(db, email, "<m1>:confirm", "Pokémon Scarlet Violet Elite Trainer Box", 2, 76.2)
send(db, email, "<m2>:ship", "Squishmallows Plush Bundle", 2)
check("unrelated names never adopt each other", len(rows(db)), 2)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
