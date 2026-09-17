"""
main.py
-------
The email connector process. One job, repeated on a timer:

  1. Connect to the mailbox over IMAP.
  2. List every message newer than the last processed UID (see state.py).
  3. For each, classify() + parse -> zero or more claims (see ingest.py).
  4. POST each claim to the backend (see api_client.py) -- the same
     POST /orders contract a Discord checkout uses, so claim resolution,
     cart/line matching and inventory creation all happen exactly the
     way they already do for Discord.
  5. Persist the new high-water mark, but ONLY after every message in
     this batch posted successfully -- see run_once()'s docstring for why
     partial progress is never saved.

Run it with: python src/main.py
Requires the backend running first (../backend/run.sh) -- checked at
startup so this fails loudly and immediately, same discipline as bot.py.

NOT YET WIRED INTO A LAUNCHAGENT: bot_service.py manages the Discord bot
as a background service Settings can start/stop; nothing equivalent
exists for this connector yet (see cache-email-primary-architecture
memory for the status). Run this by hand for now, same as DiscordConnect.
tsx's own "Prefer to run it yourself?" fallback already offers Discord
users: `cd email_ingest && ./run.sh`.
"""

import sys
import time
from typing import Optional

import config
import state
from api_client import ApiClient
from classify import EmailKind, classify
from imap_client import ImapClient
from ingest import build_claims, parse_email_date


def run_once(api: ApiClient) -> None:
    """One poll cycle: connect, list candidates since the last UID,
    classify + parse + post each one, then advance the high-water mark.

    UIDVALIDITY-aware: if the mailbox's UIDVALIDITY has changed since the
    last run (a real but rare event -- a full mailbox rebuild on Gmail's
    side), the persisted last_uid no longer means anything against the
    new numbering, so this rescans from the top rather than silently
    skipping mail or, worse, misreading unrelated messages as if they
    were the ones a stale UID used to point to.

    Saves the new high-water mark ONLY after every candidate this cycle
    posted without raising -- advancing it after a partial batch would
    permanently skip whatever came after the one that failed, since nothing
    would ever ask for those UIDs again. A message that posts successfully
    this cycle but fails to be the LAST one processed if a later one in
    the same batch raises simply gets re-posted next cycle too; POST
    /orders' dedup on (source_id, external_id) makes that a safe no-op.
    """
    saved = state.load()

    with ImapClient() as imap:
        current_validity = imap.uidvalidity()
        stale = saved.get("uidvalidity") != current_validity
        since_uid: Optional[int] = None if stale else saved.get("last_uid")
        if stale and saved:
            print(f"Mailbox UIDVALIDITY changed ({saved.get('uidvalidity')} -> {current_validity}) -- rescanning from the top.")

        candidates = imap.list_candidates(since_uid)
        if not candidates:
            return

        source_id = api.get_or_create_source()
        highest_uid = since_uid or 0
        posted = 0
        skipped = 0

        for candidate in candidates:
            highest_uid = max(highest_uid, candidate.uid)

            # Classify by SUBJECT ALONE first -- cheap, no IMAP round
            # trip -- and only FETCH the full body for a message classify()
            # actually recognizes. Most of an inbox's history is neither
            # Pokemon Center, Target, nor Walmart order mail (see
            # imap_client.py's module docstring); downloading every body
            # up front would be exactly the wasteful thing that docstring
            # says this design avoids.
            classification = classify(candidate.subject)
            if classification.retailer is None or classification.kind == EmailKind.UNRECOGNIZED:
                skipped += 1
                continue

            received_at = parse_email_date(candidate.date)
            body = imap.fetch_plaintext_body(candidate.uid)
            # build_claims() re-runs classify() on the subject internally
            # -- redundant with the check above, but negligible next to
            # the body FETCH just made, and it keeps build_claims() a
            # self-contained, independently testable unit (see
            # tests/test_ingest.py) rather than one that trusts a
            # classification its caller computed separately.
            claims = build_claims(candidate.subject, body, candidate.message_id, received_at)
            if not claims:
                skipped += 1
                continue
            for claim in claims:
                api.post_claim(claim.to_payload(), source_id)
                posted += 1

        state.save({"last_uid": highest_uid, "uidvalidity": current_validity})
        api.mark_source_synced()
        print(f"Processed {len(candidates)} message(s): {posted} claim(s) posted, {skipped} not order-shaped mail.")


def main() -> None:
    api = ApiClient()
    if not api.health_check():
        print(
            f"Can't reach the backend at {config.API_BASE_URL}. "
            f"Start it first: cd ../backend && ./run.sh",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Watching {config.EMAIL_ADDRESS} via {config.IMAP_HOST}, polling every {config.POLL_SECONDS}s.")
    try:
        while True:
            try:
                run_once(api)
            except Exception as exc:  # never let one bad poll end the loop
                print(f"(poll failed: {exc!r} -- will retry next cycle)", file=sys.stderr)
            time.sleep(config.POLL_SECONDS)
    finally:
        api.close()


if __name__ == "__main__":
    main()
