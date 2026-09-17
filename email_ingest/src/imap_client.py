"""
imap_client.py
---------------
Thin IMAP wrapper: connects, lists candidate messages, and returns a
message's plaintext body. Read-only against the mailbox -- SELECTs
INBOX in readonly mode and every FETCH uses BODY.PEEK[...] specifically
so fetching a message never marks it \\Seen. This is the user's own
personal inbox, not a dedicated ingestion mailbox; Cache should be able
to read it without changing what the user sees when they next open Gmail.

TWO-PHASE FETCH, not "download everything": list_candidates() fetches
only each message's Subject/Message-ID/Date -- cheap, small, one round
trip for the whole batch. classify.py decides from the subject alone
which of those are worth a full body fetch; only those get a second,
per-message FETCH via fetch_plaintext_body(). On an inbox with years of
history, most messages are neither Pokemon Center nor Target nor Walmart
order mail -- downloading every body up front would be the expensive,
wasteful version of this.

UID, NOT SEQUENCE NUMBER, is the cursor state.py persists: IMAP UIDs are
assigned once per mailbox and never reused (so long as UIDVALIDITY
hasn't changed -- see uidvalidity() and main.py's use of it), while
sequence numbers shift every time a message anywhere in the mailbox is
deleted, making them useless as something to persist across runs.
"""

import email
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import default as _default_policy
from imaplib import IMAP4_SSL
from typing import Optional

import config
from html_to_text import html_to_text

_UIDVALIDITY_RE = re.compile(r"UIDVALIDITY (\d+)")


@dataclass
class Candidate:
    uid: int
    subject: str
    message_id: str
    # Raw Date header text (RFC 2822, e.g. "Tue, 16 Sep 2026 23:10:24
    # +0000") -- ingest.py parses this into OrderCreate.occurred_at via
    # email.utils.parsedate_to_datetime. Kept raw here rather than
    # parsed, so imap_client stays free of any opinion about what a
    # caller does with it.
    date: str


class ImapClient:
    """Context manager: `with ImapClient() as imap: ...` logs in on
    enter and always logs out on exit, success or not -- an app password
    is a real credential and a leaked/long-lived session on Gmail's side
    serves nobody."""

    def __init__(self) -> None:
        self._conn: Optional[IMAP4_SSL] = None

    def __enter__(self) -> "ImapClient":
        self._conn = IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
        self._conn.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
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
        """The mailbox's current UIDVALIDITY, so main.py can tell a
        persisted last_uid is still meaningful. Returns None (rather than
        raising) on anything unexpected -- the caller treats that the
        same as a changed value, i.e. safest to rescan from the top."""
        assert self._conn is not None
        typ, data = self._conn.status("INBOX", "(UIDVALIDITY)")
        if typ != "OK" or not data or not data[0]:
            return None
        m = _UIDVALIDITY_RE.search(data[0].decode(errors="replace"))
        return m.group(1) if m else None

    def list_candidates(self, since_uid: Optional[int]) -> list[Candidate]:
        """Every message newer than since_uid (or the whole mailbox when
        None -- a first run, or a UIDVALIDITY change), as
        (uid, subject, message_id). classify.py decides which of these
        are worth fetch_plaintext_body()."""
        assert self._conn is not None
        criteria = f"{since_uid + 1}:*" if since_uid else "1:*"
        typ, data = self._conn.uid("search", None, criteria)
        if typ != "OK" or not data or not data[0]:
            return []
        uids = [int(x) for x in data[0].split()]
        if since_uid:
            # Known IMAP gotcha: when "N:*" has N past the mailbox's
            # highest UID (nothing new since last time), some servers
            # resolve the reversed range by swapping the endpoints and
            # returning the message AT the highest UID -- i.e. exactly
            # the one already processed last cycle. Filtering to > since_uid
            # here is what stops that from re-surfacing as a "new" message
            # and re-posting a claim that's already been sent.
            uids = [u for u in uids if u > since_uid]
        if not uids:
            return []

        out: list[Candidate] = []
        uid_set = ",".join(str(u) for u in uids)
        typ, msg_data = self._conn.uid(
            "fetch", uid_set, "(UID BODY.PEEK[HEADER.FIELDS (SUBJECT MESSAGE-ID DATE)])"
        )
        if typ != "OK":
            return []

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
        return content
