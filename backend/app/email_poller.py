"""
email_poller.py
----------------
Polls the connected mailbox on a timer and turns matching mail into
orders -- IN-PROCESS, as a background thread inside the backend, not a
separate script/service. Started automatically at backend startup (see
main.py's lifespan) whenever email is already configured, and
started/restarted/stopped directly whenever Settings saves or clears the
connection (see routers/email_account.py) -- no LaunchAgent, no second
venv, no "Install background service" button. The user's own framing:
"I want to put in the email, app password, and for it to work."

WHY THIS BELONGS IN-PROCESS, UNLIKE THE DISCORD BOT: the bot holds a
persistent gateway connection and Cache being closed shouldn't stop
checkouts being logged live -- that's a real reason to be a separate,
always-on process. Email has neither constraint. A message sitting in an
inbox is still there the next time Cache opens and polls it; nothing is
lost by only checking while the app (and its backend) is running. So the
separate-process shape bought email nothing but the exact setup friction
it now doesn't have.

THREAD, NOT ASYNCIO TASK: imaplib is fully synchronous/blocking, and
wrapping every call in a thread-pool executor to fit FastAPI's event loop
would be more code for no real benefit here -- this loop's only job is
"wake up, do blocking I/O, sleep," which a plain daemon thread does
directly. `daemon=True` so it can never keep the process alive past
`main.py` wanting to exit.

STATE LIVES ON THE Source ROW NOW, NOT A LOCAL JSON FILE: the original
email_ingest/ project kept the IMAP high-water mark (last_uid,
uidvalidity) in ~/.cache-venvs/cache-email/state.json specifically
because sources.py had no way to update a Source's config after creation
and this ran as a separate process anyway. Running in-process removes
both reasons: this module already has a live DB session, so the natural
place for "how far this source has synced" is the same Source.config
JSON blob Discord's own sync state already lives in spirit (see
models.Source's docstring) -- one less file, one less thing that can
drift from what the database itself believes.
"""

import sys
import threading
from typing import Optional

from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import SessionLocal
from app.email_ingest.classify import EmailKind, classify
from app.email_ingest.imap_client import ImapClient
from app.email_ingest.ingest import build_claims, parse_email_date
from app.routers.email_account import _read_env

POLL_SECONDS = 120

_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event] = None


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def start() -> None:
    """Starts the poller if it isn't already running, using whatever
    credential is currently saved. A no-op if email isn't configured or
    the poller is already up -- safe to call unconditionally from
    startup and from routers/email_account.py after every save."""
    global _thread, _stop_event
    if is_running():
        return

    values = _read_env()
    address = values.get("EMAIL_ADDRESS")
    app_password = values.get("EMAIL_APP_PASSWORD")
    if not address or not app_password:
        return

    _stop_event = threading.Event()
    _thread = threading.Thread(
        target=_run_forever, args=(_stop_event, address, app_password), daemon=True, name="email-poller"
    )
    _thread.start()


def stop() -> None:
    """Signals the loop to stop and waits for the current cycle to
    finish -- called on backend shutdown and whenever Settings clears
    the email connection or saves a new credential (stop then start,
    rather than mutating a running thread's credentials in place)."""
    global _thread, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=30)
    _thread = None
    _stop_event = None


def restart() -> None:
    """Called after Settings saves a changed address/app password --
    the running thread captured the OLD credential as a plain argument,
    so there's nothing to hot-swap; stop and start fresh instead. Cheap:
    the loop's own state lives on the Source row, not in the thread, so
    nothing is lost by doing this."""
    stop()
    start()


def _run_forever(stop_event: threading.Event, address: str, app_password: str) -> None:
    print(f"[email] watching {address}, polling every {POLL_SECONDS}s.")
    while not stop_event.is_set():
        try:
            _run_once(address, app_password)
        except Exception as exc:  # never let one bad cycle end the loop
            print(f"[email] poll failed: {exc!r} -- will retry next cycle", file=sys.stderr)
        stop_event.wait(POLL_SECONDS)


def _get_or_create_source(db: Session, address: str) -> models.Source:
    """
    Matched on BOTH type AND config["email"] -- NOT type alone. Found
    live (2026-09-17): an earlier manual test had left a stray
    'email_account' Source behind (config.email="test@example.com"), and
    filtering by type only meant an unordered `.first()` could return
    EITHER row depending on query-plan happenstance -- confirmed: one
    poll cycle wrote its high-water mark onto the real account's row,
    the next onto the stray test row, each silently starting the other
    from scratch. Filtering in Python (a handful of rows, not worth a
    JSON-column query) is what actually pins this to the ONE source that
    describes the currently configured address, matching a still-
    configured credential in email_account.py to the exact row this
    poller reads and writes state on.
    """
    user = crud.get_or_create_default_user(db)
    for candidate in db.query(models.Source).filter_by(user_id=user.id, type="email_account"):
        if (candidate.config or {}).get("email") == address:
            return candidate
    source = models.Source(
        user_id=user.id,
        type="email_account",
        name=f"email: {address}",
        config={"email": address, "provider": "gmail"},
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _run_once(address: str, app_password: str) -> None:
    """
    One poll cycle. THREE failure modes, told apart by whether retrying
    could ever help -- same discipline the original standalone connector
    used, adapted now that there's no HTTP layer to draw the line at:

      PARSING a candidate's body (fetch_plaintext_body + build_claims)
      raising is treated as THAT MESSAGE's own permanent problem --
      logged, the UID cursor still advances past it, loop continues.
      Retrying a malformed MIME part / encoding edge case would fail
      identically forever.

      INGESTING a claim (schemas.OrderCreate validation, or
      crud.ingest_order itself) raising is the same kind of permanent
      problem, just one step later -- logged and skipped, not retried,
      for the same reason. There is no longer an HTTP status code to
      branch on (this is a direct function call now, not a POST), so
      this catches Exception broadly at the per-claim level rather than
      distinguishing 4xx from 5xx the way the old httpx-based version
      did -- there is no analogous "backend down" failure mode anymore
      when ingestion is a plain Python call in the same process.

      The IMAP CONNECTION itself (login, or anything before the
      candidate loop starts) failing is NOT caught here -- it propagates
      out of _run_once(), so the new high-water mark is never saved this
      cycle and _run_forever's own try/except logs it and retries next
      cycle. That kind IS plausibly transient (a network blip, Gmail
      briefly unreachable).
    """
    db = SessionLocal()
    try:
        source = _get_or_create_source(db, address)
        config = dict(source.config or {})
        saved_uid = config.get("last_uid")
        saved_validity = config.get("uidvalidity")

        with ImapClient(address, app_password) as imap:
            current_validity = imap.uidvalidity()
            stale = saved_validity != current_validity
            since_uid: Optional[int] = None if stale else saved_uid
            if stale and saved_validity:
                print(f"[email] mailbox UIDVALIDITY changed ({saved_validity} -> {current_validity}) -- rescanning recent mail.")

            candidates = imap.list_candidates(since_uid)
            if not candidates:
                return

            highest_uid = since_uid or 0
            posted = skipped = failed = 0

            for candidate in candidates:
                highest_uid = max(highest_uid, candidate.uid)

                # Classify by SUBJECT ALONE first -- cheap, no IMAP round
                # trip -- and only FETCH the full body for a message
                # classify() actually recognizes.
                classification = classify(candidate.subject)
                if classification.retailer is None or classification.kind == EmailKind.UNRECOGNIZED:
                    skipped += 1
                    continue

                received_at = parse_email_date(candidate.date)
                try:
                    body = imap.fetch_plaintext_body(candidate.uid)
                    claims = build_claims(candidate.subject, body, candidate.message_id, received_at)
                except Exception as exc:
                    print(f"[email] couldn't parse uid={candidate.uid} subject={candidate.subject!r}: {exc!r}", file=sys.stderr)
                    failed += 1
                    continue

                if not claims:
                    skipped += 1
                    continue

                for claim in claims:
                    try:
                        order_in = schemas.OrderCreate(**claim.to_payload(), source_id=source.id)
                        crud.ingest_order(db, order_in)
                        posted += 1
                    except Exception as exc:
                        print(f"[email] claim rejected, external_id={claim.external_id}: {exc!r}", file=sys.stderr)
                        db.rollback()
                        failed += 1

            source.config = {**config, "last_uid": highest_uid, "uidvalidity": current_validity}
            db.commit()
            print(f"[email] processed {len(candidates)} message(s): {posted} claim(s) ingested, {skipped} not order-shaped mail, {failed} failed.")
    finally:
        db.close()
