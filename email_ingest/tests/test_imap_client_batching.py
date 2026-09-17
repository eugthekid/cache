"""
Verifies imap_client.ImapClient.list_candidates() chunks a large UID set
into multiple FETCH calls rather than joining all of them into one command
-- the fix for a first run against a mailbox with years of history
potentially matching thousands of UIDs (the initial SEARCH has no content
filter; see the module docstring) into one arbitrarily long comma-joined
FETCH argument, betting on an unstated IMAP server line-length limit.

No live IMAP connection: a minimal fake stands in for imaplib's
IMAP4_SSL just for the one method list_candidates() calls directly
(`.uid("search", ...)`); _fetch_headers (the per-batch FETCH) is
monkey-patched to just record what it was called with, since verifying
its own real-IMAP response parsing is the parser tests' job, not this
one's -- this test is only about the chunking boundary.

Needs the connector's own runtime dependencies (imap_client.py imports
config.py, which imports python-dotenv) and EMAIL_ADDRESS/
EMAIL_APP_PASSWORD set in the environment -- same as
test_main_resilience.py, see that file's docstring.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from imap_client import Candidate, ImapClient

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


class FakeConn:
    """Only implements what list_candidates() itself calls directly:
    uid("search", ...). Returns imaplib's actual response shape for a
    SEARCH -- (typ, [b"1 2 3 ... N"])."""

    def __init__(self, uids: list[int]):
        self._response = (" ".join(str(u) for u in uids)).encode()

    def uid(self, command, *args):
        assert command == "search"
        return "OK", [self._response]


client = ImapClient()
client._conn = FakeConn(list(range(1, 1201)))  # 1200 UIDs, no gaps

calls: list[list[int]] = []


def fake_fetch_headers(self, uids):
    calls.append(list(uids))
    return [Candidate(uid=u, subject="x", message_id=f"m{u}", date="") for u in uids]


with patch.object(ImapClient, "_fetch_headers", fake_fetch_headers):
    result = client.list_candidates(since_uid=None)

check("1200 UIDs split into 3 batches of <= 500 each", len(calls), 3)
if len(calls) == 3:
    check("batch sizes are 500, 500, 200", [len(c) for c in calls], [500, 500, 200])
    check("batches cover every UID once, in order, no gaps or overlap", calls[0] + calls[1] + calls[2], list(range(1, 1201)))
check("all 1200 candidates returned", len(result), 1200)

# Exactly-one-batch-worth (500) shouldn't create a spurious empty second batch.
calls.clear()
client._conn = FakeConn(list(range(1, 501)))
with patch.object(ImapClient, "_fetch_headers", fake_fetch_headers):
    client.list_candidates(since_uid=None)
check("exactly 500 UIDs -> exactly 1 batch, not 2", len(calls), 1)

# A tiny mailbox (the common case) shouldn't be affected at all.
calls.clear()
client._conn = FakeConn([1, 2, 3])
with patch.object(ImapClient, "_fetch_headers", fake_fetch_headers):
    client.list_candidates(since_uid=None)
check("3 UIDs -> 1 batch of 3 (unchanged from before batching existed)", calls, [[1, 2, 3]])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
