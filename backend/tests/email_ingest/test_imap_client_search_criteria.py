"""
Pins the exact IMAP search string list_candidates() sends for an
incremental poll -- the bug this guards against can't be caught by
mocking a fake IMAP client the way test_email_poller.py does, because the
bug is IN the criteria string ImapClient itself constructs, not in how a
caller uses the response.

THE BUG, FOUND LIVE (2026-09-18): list_candidates(since_uid=N) built the
criteria string as f"{N+1}:* ALL" and called it through
self._conn.uid("search", None, criteria). The IMAP protocol semantics
(RFC 3501 6.4.8) say a UID-command wrapper should make every number
inside the criteria mean a UID, but Gmail parses the bare "N+1:*"
sequence-set as a message SEQUENCE NUMBER range regardless. Since every
real since_uid is an actual UID (order of 10^5-10^6) and Gmail sequence
numbers only run 1..total-message-count, that range was essentially
always out of bounds -- confirmed live: mailbox had 121,239 messages
total against since_uid=288600, and the bare form returned exactly ONE
message (the single newest one overall, the documented reversed-range
gotcha resolving out-of-range) instead of the 42 real UIDs
"UID 288601:* ALL" correctly returns. Every incremental poll cycle was
silently starved to "at most the one newest message in the whole
mailbox" -- a morning's worth of real order confirmation emails landed
in one poll window and all but one were dropped, no error raised
anywhere, because a valid-but-wrong search returning fewer rows looks
identical to "nothing new."

Fix: the criteria string must spell "UID" itself
(f"UID {N+1}:* ALL"), not rely on the .uid() method call alone.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.imap_client import ImapClient

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


client = ImapClient("addr@example.com", "app-password")
client._conn = MagicMock()
client._conn.uid.return_value = ("OK", [b""])

client.list_candidates(since_uid=288600)

call_args = client._conn.uid.call_args
check("search was called via the uid() wrapper", call_args.args[0], "search")
criteria = call_args.args[2]
check("criteria explicitly spells UID before the range (not just relying on .uid())", criteria, "UID 288601:* ALL")
check("criteria does NOT send the bug's bare sequence-set form", criteria != "288601:* ALL", True)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
