"""
Exercises main.run_once()'s actual control flow against hand-written fake
ImapClient/ApiClient stand-ins, swapped in via unittest.mock.patch.object
(stdlib, no extra dependency) -- everything else in this directory tests
pure functions directly with no patching at all; this is the one file
that has to reach for it, because main.py is deliberately the one module
that's all I/O orchestration. No live IMAP or backend needed either way.

THE BUG THIS PROVES FIXED: a message whose body fails to PARSE (a
malformed MIME part, an encoding edge case) used to raise straight out of
the candidate loop, aborting run_once() before state.save() ever ran.
Since the next poll cycle re-asks for the same since_uid range, it would
hit the exact same "poison pill" message and fail identically -- forever.
Every message that arrived after it in the mailbox would never be
processed either, silently, with nothing distinguishing "backend is
momentarily down" from "permanently stuck" in the logs. Verified fixed:
a batch with a poison-pill message in the middle still processes what
comes after it, and the UID cursor advances past all of it.

UNLIKE EVERY OTHER TEST IN THIS DIRECTORY, this one needs the connector's
own runtime dependencies (httpx, python-dotenv) just to import main.py,
and needs EMAIL_ADDRESS/EMAIL_APP_PASSWORD set in the environment for
config.py's own startup check to pass. Run it from
~/.cache-venvs/cache-email/bin/python (or any venv with
requirements.txt installed) with those two set -- not the bare system
python3 every other test here works fine under.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import main
from imap_client import Candidate

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


class FakeImapClient:
    """Stands in for imap_client.ImapClient. Candidates and bodies are
    pre-baked; fetch_plaintext_body raises for whichever UID is in
    `poison_uids`, simulating a message main.py's classify-then-fetch
    step successfully classified but then failed to actually parse."""

    def __init__(self, candidates, bodies, poison_uids=frozenset()):
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


def _fake_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://test/orders")
    response = httpx.Response(status_code, request=request, text="simulated rejection")
    return httpx.HTTPStatusError("simulated", request=request, response=response)


class FakeApiClient:
    """Stands in for api_client.ApiClient. Records every posted payload;
    raise_on_external_id + raise_kind let a test simulate one specific
    claim failing to POST, either as a genuine network problem
    ("network", a plain ConnectionError -- main.py doesn't catch this,
    same as any other unexpected exception) or as the backend rejecting
    the payload outright ("rejected", an httpx.HTTPStatusError with a
    4xx status -- main.py DOES specifically catch this one and treat it
    as permanent, see run_once()'s docstring)."""

    def __init__(self, raise_on_external_id=None, raise_kind="network"):
        self.posted: list[dict] = []
        self._raise_on_external_id = raise_on_external_id
        self._raise_kind = raise_kind
        self.synced = False

    def get_or_create_source(self):
        return "source-1"

    def post_claim(self, payload, source_id):
        if payload.get("external_id") == self._raise_on_external_id:
            if self._raise_kind == "rejected":
                raise _fake_http_status_error(422)
            raise ConnectionError("simulated backend unreachable")
        self.posted.append(payload)
        return {"id": "order-x"}

    def mark_source_synced(self):
        self.synced = True


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


# --- scenario 1: poison pill in the middle of a batch --------------------
candidates = [
    Candidate(uid=1, subject=PC_CONFIRM_SUBJECT, message_id="msg-1", date="Wed, 15 Jul 2026 09:00:00 +0000"),
    Candidate(uid=2, subject=PC_CONFIRM_SUBJECT, message_id="msg-2-poison", date="Wed, 15 Jul 2026 09:01:00 +0000"),
    Candidate(uid=3, subject=PC_CONFIRM_SUBJECT, message_id="msg-3", date="Wed, 15 Jul 2026 09:02:00 +0000"),
]
bodies = {1: GOOD_BODY, 2: "irrelevant -- fetch raises before this is used", 3: GOOD_BODY}
fake_imap = FakeImapClient(candidates, bodies, poison_uids={2})
fake_api = FakeApiClient()

captured_state: dict = {}
with patch.object(main, "ImapClient", lambda: fake_imap), \
     patch.object(main.state, "load", lambda: {}), \
     patch.object(main.state, "save", lambda data: captured_state.update(data)):
    main.run_once(fake_api)

check("message 1 (before the poison pill) still posted", any(p["external_id"] == "msg-1:confirm:0" for p in fake_api.posted), True)
check("message 3 (after the poison pill) still posted -- not blocked", any(p["external_id"] == "msg-3:confirm:0" for p in fake_api.posted), True)
check("poison message itself never posted anything", any("msg-2-poison" in p["external_id"] for p in fake_api.posted), False)
check("UID cursor advanced PAST the poison pill (uid=3), not stuck at/before it", captured_state.get("last_uid"), 3)
check("all 3 candidates were at least attempted (fetch called for each)", sorted(fake_imap.fetched_uids), [1, 2, 3])

# --- scenario 2: a second run with the SAME since_uid never re-fetches the
# poison message again (proves the cursor advancing actually matters, not
# just that this run's state object happened to say 3) ---------------------
fake_imap_2 = FakeImapClient(candidates, bodies, poison_uids={2})
fake_api_2 = FakeApiClient()
with patch.object(main, "ImapClient", lambda: fake_imap_2), \
     patch.object(main.state, "load", lambda: {"last_uid": 3, "uidvalidity": "1"}), \
     patch.object(main.state, "save", lambda data: None):
    main.run_once(fake_api_2)
check("next cycle (since_uid=3): nothing left to process, poison message not re-fetched", fake_imap_2.fetched_uids, [])

# --- scenario 3: a POST failure (not a parse failure) still aborts the
# batch and does NOT advance state -- the deliberately different behavior
# documented in run_once()'s docstring, so this proves the two failure
# modes are genuinely handled differently, not that everything is now
# swallowed indiscriminately. All three messages parse fine this time
# (a fresh candidates/bodies set, no poison_uids) -- only the POST for the
# second one is made to fail. -----------------------------------------------
candidates_3 = [
    Candidate(uid=1, subject=PC_CONFIRM_SUBJECT, message_id="msg-1", date="Wed, 15 Jul 2026 09:00:00 +0000"),
    Candidate(uid=2, subject=PC_CONFIRM_SUBJECT, message_id="msg-2", date="Wed, 15 Jul 2026 09:01:00 +0000"),
    Candidate(uid=3, subject=PC_CONFIRM_SUBJECT, message_id="msg-3", date="Wed, 15 Jul 2026 09:02:00 +0000"),
]
bodies_3 = {1: GOOD_BODY, 2: GOOD_BODY, 3: GOOD_BODY}
fake_imap_3 = FakeImapClient(candidates_3, bodies_3, poison_uids=frozenset())
fake_api_3 = FakeApiClient(raise_on_external_id="msg-2:confirm:0")
saved_state_3 = {"called": False}
with patch.object(main, "ImapClient", lambda: fake_imap_3), \
     patch.object(main.state, "load", lambda: {}), \
     patch.object(main.state, "save", lambda data: saved_state_3.update(called=True)):
    try:
        main.run_once(fake_api_3)
        raised = False
    except ConnectionError:
        raised = True
check("a POST failure (not a parse failure) propagates out of run_once()", raised, True)
check("...and state.save() is correctly never reached that cycle", saved_state_3["called"], False)
check("message 1's claim still posted before the failure (partial progress, safely re-postable next cycle)", any(p["external_id"] == "msg-1:confirm:0" for p in fake_api_3.posted), True)

# --- scenario 4: the backend REJECTING a claim (a 4xx) is a third,
# distinct failure mode from both of the above -- treated like a parse
# failure (permanent, log + skip + keep going), NOT like a network
# failure (transient, abort + retry). Without this, a genuinely bad
# payload would retry forever, identically to the original poison-pill
# bug this whole file exists to catch, just one step later in the
# pipeline. -----------------------------------------------------------------
candidates_4 = [
    Candidate(uid=1, subject=PC_CONFIRM_SUBJECT, message_id="msg-1", date="Wed, 15 Jul 2026 09:00:00 +0000"),
    Candidate(uid=2, subject=PC_CONFIRM_SUBJECT, message_id="msg-2-rejected", date="Wed, 15 Jul 2026 09:01:00 +0000"),
    Candidate(uid=3, subject=PC_CONFIRM_SUBJECT, message_id="msg-3", date="Wed, 15 Jul 2026 09:02:00 +0000"),
]
bodies_4 = {1: GOOD_BODY, 2: GOOD_BODY, 3: GOOD_BODY}
fake_imap_4 = FakeImapClient(candidates_4, bodies_4, poison_uids=frozenset())
fake_api_4 = FakeApiClient(raise_on_external_id="msg-2-rejected:confirm:0", raise_kind="rejected")
captured_state_4: dict = {}
with patch.object(main, "ImapClient", lambda: fake_imap_4), \
     patch.object(main.state, "load", lambda: {}), \
     patch.object(main.state, "save", lambda data: captured_state_4.update(data)):
    main.run_once(fake_api_4)  # must NOT raise -- a 4xx is handled, not propagated

check("message 1 still posted", any(p["external_id"] == "msg-1:confirm:0" for p in fake_api_4.posted), True)
check("message 3 (after the rejected one) still posted -- not blocked", any(p["external_id"] == "msg-3:confirm:0" for p in fake_api_4.posted), True)
check("the rejected claim itself never appears as posted", any("msg-2-rejected" in p["external_id"] for p in fake_api_4.posted), False)
check("UID cursor still advances past the rejected message's UID", captured_state_4.get("last_uid"), 3)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
