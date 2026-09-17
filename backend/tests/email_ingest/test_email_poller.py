"""
Exercises app/email_poller.py's real logic -- _get_or_create_source() and
_run_once()'s failure handling -- against a REAL in-memory SQLite
database (not mocked), using a fake ImapClient stand-in for the one thing
that can't run in a test: an actual IMAP connection. Everything else
(crud.ingest_order, Source/Order/IngestedMessage rows) is the genuine
code path, run against a throwaway :memory: engine.

THE BUG THIS FILE'S FIRST TEST PROVES FIXED, FOUND LIVE (2026-09-17):
_get_or_create_source() used to match on Source.type alone. The first
real end-to-end run left a stray 'email_account' Source behind from an
earlier manual curl test (config.email="test@example.com"); once a
SECOND real Source existed for the real address, an unordered `.first()`
query could return EITHER row on any given poll cycle -- confirmed live:
one cycle wrote its high-water mark and orders onto the real account's
row, the next onto the stray test row, silently alternating. 14 real
orders ended up duplicated before this was caught and the two Source
rows manually merged back together. Matching on config["email"] too, not
just type, is what stops two Sources of the same type from ever being
interchangeable.

THE SECOND TEST is the direct descendant of the deleted email_ingest/
project's test_main_resilience.py -- same poison-pill-isolation property
(a message that fails to PARSE must not block the ones after it, and the
UID cursor must still advance past it), now proven against
email_poller._run_once directly instead of the standalone main.py this
replaced.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models, email_poller
from app.email_ingest.imap_client import Candidate

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


# --- in-memory DB, same schema as the real app -----------------------------
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine)


def make_user_and_db():
    db = TestSession()
    user = models.User(email="local@inventory-tracker")
    db.add(user)
    db.commit()
    db.refresh(user)
    return db, user


# --- test 1: source matching is scoped to email, not just type -------------
db, user = make_user_and_db()

stray = models.Source(user_id=user.id, type="email_account", name="gmail: test", config={"email": "test@example.com", "provider": "gmail"})
db.add(stray)
db.commit()

real_address = "eugeneseo4816@gmail.com"
found = email_poller._get_or_create_source(db, real_address)
check("a stray same-type Source with a DIFFERENT email is never matched", found.id != stray.id, True)
check("a fresh Source is created for the real address instead", found.config.get("email"), real_address)

# Calling it again must return the SAME row, not create a second one.
found_again = email_poller._get_or_create_source(db, real_address)
check("second call returns the same row (no duplicate Source created)", found_again.id, found.id)
check("still exactly one Source for the real address", db.query(models.Source).filter_by(type="email_account").count(), 2)  # stray + real

db.close()


# --- test 2: poison-pill isolation in _run_once -----------------------------
class FakeImapClient:
    """Stands in for ImapClient. fetch_plaintext_body raises for
    poison_uids, simulating a message that classify() recognized by
    subject but then failed to actually parse."""

    def __init__(self, address, app_password, candidates, bodies, poison_uids=frozenset()):
        self._candidates = candidates
        self._bodies = bodies
        self._poison_uids = poison_uids
        self.fetched_uids: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def uidvalidity(self):
        return "1"

    def list_candidates(self, since_uid):
        return [c for c in self._candidates if since_uid is None or c.uid > since_uid]

    def fetch_plaintext_body(self, uid):
        self.fetched_uids.append(uid)
        if uid in self._poison_uids:
            raise ValueError(f"simulated malformed MIME part for uid={uid}")
        return self._bodies[uid]


PC_CONFIRM_SUBJECT = "Thank you for shopping at PokemonCenter.com!"
GOOD_BODY = """ Pokémon Center

| |
| Order Details |
| Order Number: P0000000001 Date Ordered: July 15, 2026 |

| |
| Order Summary |

| |
| Pokémon TCG: Some Product |
| SKU #: 10-00000-001 Qty: 1 Price: $9.99 |

| |
| Order Subtotal | $9.99 |

| |
| Sales Tax | $0.00 |

| |
| Shipping | $0.00 |

| |
| Order Total | $9.99 |
"""

db2, user2 = make_user_and_db()

candidates = [
    Candidate(uid=1, subject=PC_CONFIRM_SUBJECT, message_id="msg-1", date="Wed, 15 Jul 2026 09:00:00 +0000"),
    Candidate(uid=2, subject=PC_CONFIRM_SUBJECT, message_id="msg-2-poison", date="Wed, 15 Jul 2026 09:01:00 +0000"),
    Candidate(uid=3, subject=PC_CONFIRM_SUBJECT, message_id="msg-3", date="Wed, 15 Jul 2026 09:02:00 +0000"),
]
bodies = {1: GOOD_BODY, 2: "irrelevant -- fetch raises before this is used", 3: GOOD_BODY}

fake_imap = FakeImapClient("addr", "pw", candidates, bodies, poison_uids={2})

with patch.object(email_poller, "ImapClient", lambda addr, pw: fake_imap), \
     patch.object(email_poller, "SessionLocal", lambda: db2):
    email_poller._run_once("test2@example.com", "app-password")

orders = db2.query(models.Order).all()
check("message 1 (before the poison pill) still ingested", any(o.external_id == "msg-1:confirm:0" for o in orders), True)
check("message 3 (after the poison pill) still ingested -- not blocked", any(o.external_id == "msg-3:confirm:0" for o in orders), True)
check("poison message itself never created an order", any("msg-2-poison" in o.external_id for o in orders), False)

source2 = db2.query(models.Source).filter_by(type="email_account").first()
check("UID cursor advanced PAST the poison pill (uid=3), not stuck at/before it", source2.config.get("last_uid"), 3)
check("all 3 candidates were at least attempted", sorted(fake_imap.fetched_uids), [1, 2, 3])

db2.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
