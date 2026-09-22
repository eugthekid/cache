"""
imap_client.py
---------------
Thin IMAP wrapper: connects, lists candidate messages, and returns a
message's plaintext body. Read-only against the mailbox -- SELECTs
INBOX in readonly mode and every FETCH uses BODY.PEEK[...] specifically
so fetching a message never marks it \\Seen. This is the user's own
personal inbox, not a dedicated ingestion mailbox; Cache should be able
to read it without changing what the user sees when they next open Gmail.

ADAPTED FROM email_ingest/src/imap_client.py (moved into the backend
2026-09-17, see app/email_ingest/__init__.py) -- the one real change is
that credentials are constructor arguments now, not a module-level
dotenv-loaded config: the backend already has its own credential story
(app/routers/email_account.py's email.env), and this package is meant to
stay usable without a second parallel config-loading mechanism.

TWO-PHASE FETCH, not "download everything": list_candidates() fetches
only each message's Subject/Message-ID/Date -- cheap, small, one round
trip per batch. classify.py decides from the subject alone which of
those are worth a full body fetch; only those get a second, per-message
FETCH via fetch_plaintext_body(). On an inbox with years of history,
most messages are neither Pokemon Center nor Target nor Walmart order
mail -- downloading every body up front would be the expensive, wasteful
version of this.

FIRST-RUN DATE BOUND, added after a real live failure (2026-09-17): an
unbounded first scan (since_uid=None, "search the entire mailbox") on a
real, years-old Gmail account raised `abort('command: UID => socket
error: EOF')` -- Gmail hung up mid-command rather than returning however
many thousands of UIDs an unbounded SEARCH 1:* matched. FIRST_RUN_DAYS
bounds that initial search to recent history instead; every later poll
is already naturally bounded to "since the last UID seen," so this only
matters once, the very first time a mailbox is ever connected. Real cost:
older order history beyond that window won't be picked up by an ordinary
poll -- a deliberate trade for "the connector actually starts," not
something to silently widen later without deciding that trade-off is
worth revisiting.

UID, NOT SEQUENCE NUMBER, is the cursor app/email_poller.py persists:
IMAP UIDs are assigned once per mailbox and never reused (so long as
UIDVALIDITY hasn't changed -- see uidvalidity() and the poller's use of
it), while sequence numbers shift every time a message anywhere in the
mailbox is deleted, making them useless as something to persist across
runs.
"""

import email
import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.policy import default as _default_policy
from imaplib import IMAP4_SSL
from typing import Optional

from .html_to_text import html_to_text

_UIDVALIDITY_RE = re.compile(r"UIDVALIDITY (\d+)")

# See module docstring. 180 days is generous enough to cover an active
# reseller's recent, still-actionable order history without risking the
# same failure this exists to prevent.
FIRST_RUN_DAYS = 180


@dataclass
class Candidate:
    uid: int
    subject: str
    message_id: str
    # Raw Date header text (RFC 2822, e.g. "Tue, 16 Sep 2026 23:10:24
    # +0000") -- app/email_ingest/ingest.py parses this into
    # OrderCreate.occurred_at via email.utils.parsedate_to_datetime. Kept
    # raw here rather than parsed, so imap_client stays free of any
    # opinion about what a caller does with it.
    date: str


class ImapClient:
    """Context manager: `with ImapClient(address, app_password) as imap:
    ...` logs in on enter and always logs out on exit, success or not --
    an app password is a real credential and a leaked/long-lived session
    on Gmail's side serves nobody."""

    def __init__(self, email_address: str, app_password: str, host: str = "imap.gmail.com", port: int = 993) -> None:
        self._email_address = email_address
        self._app_password = app_password
        self._host = host
        self._port = port
        self._conn: Optional[IMAP4_SSL] = None

    def __enter__(self) -> "ImapClient":
        self._conn = IMAP4_SSL(self._host, self._port)
        self._conn.login(self._email_address, self._app_password)
        # readonly=True is belt-and-suspenders with BODY.PEEK below --
        # PEEK already avoids setting \Seen, but a readonly SELECT also
        # blocks any other flag-changing command from silently working.
        self._conn.select("INBOX", readonly=True)
        return self

    def __exit__(self, *exc_info) -> None:
        if self._conn is None:
            return
        try:
            self._conn.close()
        except Exception:
            pass
        try:
            self._conn.logout()
        except Exception:
            pass

    def uidvalidity(self) -> Optional[str]:
        """The mailbox's current UIDVALIDITY, so the poller can tell a
        persisted last_uid is still meaningful. Returns None (rather than
        raising) on anything unexpected -- the caller treats that the
        same as a changed value, i.e. safest to rescan from the top."""
        assert self._conn is not None
        typ, data = self._conn.status("INBOX", "(UIDVALIDITY)")
        if typ != "OK" or not data or not data[0]:
            return None
        m = _UIDVALIDITY_RE.search(data[0].decode(errors="replace"))
        return m.group(1) if m else None

    # Max UIDs joined into one FETCH command. Even with the first-run date
    # bound above, there's no guarantee an IMAP server accepts an
    # arbitrarily long comma-joined argument on one command line.
    # Chunking avoids betting on an unstated server limit; 500 is
    # comfortably small for any reasonable per-line cap while still
    # keeping the round-trip count low.
    _FETCH_BATCH_SIZE = 500

    def list_candidates(self, since_uid: Optional[int]) -> list[Candidate]:
        """Every message newer than since_uid, as (uid, subject,
        message_id, date). since_uid=None (a first run, or a UIDVALIDITY
        change) is bounded to the last FIRST_RUN_DAYS days instead of the
        whole mailbox -- see module docstring. classify.py decides which
        of these are worth fetch_plaintext_body()."""
        assert self._conn is not None
        if since_uid:
            # MUST spell "UID" inside the criteria string itself, not just
            # call the connection's .uid() method -- found live
            # (2026-09-18): .uid("search", None, "N:* ALL") sends
            # "UID SEARCH N:* ALL" at the protocol level, but Gmail still
            # parses the bare "N:*" sequence-set INSIDE that criteria as a
            # message SEQUENCE NUMBER range, not a UID range. Since every
            # persisted since_uid is a real UID (order of 10^5-10^6) and
            # the mailbox's sequence numbers only run 1..total-message-
            # count, that range is essentially always out of bounds --
            # confirmed live: mailbox had 121,239 messages total (max
            # sequence number 121239) against since_uid=288600, and the
            # bare form returned exactly ONE message, the single newest
            # one overall (the out-of-range reversed-set gotcha the
            # comment below already knew about) -- not the 42 real UIDs
            # `UID 288601:* ALL` correctly returns. This silently starved
            # every incremental poll cycle down to "catch at most the one
            # newest message in the whole mailbox", not just Target/PC
            # mail -- a burst of same-morning order confirmations landed
            # within one poll window and all but one were dropped, no
            # error raised anywhere, because a valid-but-wrong search that
            # returns fewer rows looks identical to "nothing new."
            criteria = f"UID {since_uid + 1}:* ALL"
        else:
            cutoff = (datetime.now() - timedelta(days=FIRST_RUN_DAYS)).strftime("%d-%b-%Y")
            criteria = f"SINCE {cutoff}"
        typ, data = self._conn.uid("search", None, criteria)
        if typ != "OK" or not data or not data[0]:
            return []
        uids = [int(x) for x in data[0].split()]
        if since_uid:
            # Known IMAP gotcha, kept as a second line of defense even
            # with the explicit "UID" prefix above: when "UID N:*" has N
            # past the mailbox's highest UID (nothing new since last
            # time), some servers resolve the reversed range by swapping
            # the endpoints and returning the message AT the highest UID
            # -- i.e. exactly the one already processed last cycle.
            # Filtering to > since_uid here is what stops that from
            # resurfacing as a "new" message and re-posting an
            # already-sent claim (idempotent either way, but this avoids
            # the wasted work).
            uids = [u for u in uids if u > since_uid]
        if not uids:
            return []

        out: list[Candidate] = []
        for batch_start in range(0, len(uids), self._FETCH_BATCH_SIZE):
            batch = uids[batch_start : batch_start + self._FETCH_BATCH_SIZE]
            out.extend(self._fetch_headers(batch))
        return out

    def _fetch_headers(self, uids: list[int]) -> list[Candidate]:
        assert self._conn is not None
        uid_set = ",".join(str(u) for u in uids)
        typ, msg_data = self._conn.uid(
            "fetch", uid_set, "(UID BODY.PEEK[HEADER.FIELDS (SUBJECT MESSAGE-ID DATE)])"
        )
        if typ != "OK":
            return []

        out: list[Candidate] = []
        for part in msg_data:
            if not isinstance(part, tuple):
                # imaplib interleaves a closing b')' after each message's
                # tuple -- not a message of its own, skip.
                continue
            prefix, header_bytes = part
            uid_m = re.search(rb"UID (\d+)", prefix)
            if not uid_m:
                continue
            uid = int(uid_m.group(1))
            # Parsing this tiny header block through email.message_from_bytes
            # (rather than hand-splitting lines) is what gets RFC 2047
            # MIME-encoded subjects ("=?UTF-8?B?...?=", which a non-ASCII
            # subject line -- "Pokémon" -- can legally be sent as) decoded
            # automatically; policy.default does that decoding the moment
            # the header is read as a string.
            header_msg = email.message_from_bytes(header_bytes, policy=_default_policy)
            subject = str(header_msg.get("subject", "") or "")
            message_id = str(header_msg.get("message-id", "") or "") or f"uid:{uid}"
            date = str(header_msg.get("date", "") or "")
            out.append(Candidate(uid=uid, subject=subject, message_id=message_id, date=date))
        return out

    def fetch_plaintext_body(self, uid: int) -> str:
        """The message's plaintext body -- its native text/plain MIME
        part when the message has one, else its text/html part run
        through html_to_text.html_to_text() (see that module's docstring
        for why the fallback is a known risk, not a sure thing)."""
        assert self._conn is not None
        typ, data = self._conn.uid("fetch", str(uid), "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return ""
        raw = data[0][1]
        msg: EmailMessage = email.message_from_bytes(raw, policy=_default_policy)  # type: ignore[assignment]
        body_part = msg.get_body(preferencelist=("plain", "html"))
        if body_part is None:
            return ""
        content = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            return html_to_text(content)
        # UNESCAPE EVEN THE "NATIVE" text/plain PART -- found live
        # (2026-09-18): a real Target confirmation's plain-text
        # alternative carried literal, undecoded numeric character
        # references as plain text ("Pok&#233;mon", "Mega
        # Evolution&#8212;Ascended..."), not real HTML for a parser to
        # decode -- Target's own plain-text part appears to be generated
        # by stripping tags from the HTML part without entity-decoding
        # first. html_to_text's HTMLParser(convert_charrefs=True) already
        # handles the text/html fallback branch correctly; this covers
        # the text/plain branch the same way. Splitting one Product from
        # its correctly-decoded Discord-sourced twin was the visible
        # symptom -- two rows for the same physical item because the
        # garbled name normalized differently.
        return html.unescape(content)
