"""
main.py
-------
The email connector process. One job, repeated on a timer:

  1. Connect to the mailbox over IMAP.
  2. List every message newer than the last processed UID (see state.py).
  3. For each, classify() by subject alone; skip the body FETCH entirely
     for anything unrecognized.
  4. For a recognized one, classify() + parse -> zero or more claims (see
     ingest.py). A message that fails to PARSE is logged and skipped,
     without blocking anything after it -- see run_once()'s docstring.
  5. POST each claim to the backend (see api_client.py) -- the same
     POST /orders contract a Discord checkout uses, so claim resolution,
     cart/line matching and inventory creation all happen exactly the
     way they already do for Discord.
  6. Persist the new high-water mark -- see run_once()'s docstring for
     exactly when.

Run it with: python src/main.py, or install it as a background service
from Settings -> Connect Email (backend/app/routers/email_service.py) --
same LaunchAgent pattern as the Discord bot, including automatic venv
setup, so no terminal command is required for normal use. This file is
still what actually runs either way.
Requires the backend running first (../backend/run.sh) -- checked at
startup so this fails loudly and immediately, same discipline as bot.py.
"""

import sys
import time
from typing import Optional

import httpx

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

    THREE failure modes, told apart by whether retrying could ever help --
    found by tracing what each one does to the UID cursor:

      PARSING a candidate's body (fetch_plaintext_body + build_claims)
      raising is treated as THAT MESSAGE's own permanent problem --
      logged, the UID cursor still advances past it, loop continues.
      Retrying a malformed MIME part / encoding edge case would fail
      identically forever; without this, the cursor could never move
      past it, silently blocking every real message that arrived after
      it too.

      POSTING a claim that the backend REJECTS (httpx.HTTPStatusError,
      status < 500 -- a validation error, a bad payload shape) is the
      same kind of permanent problem, just one step later in the
      pipeline: logged and skipped, not retried, for the same reason.

      POSTING a claim that fails for any OTHER reason (a network error,
      a 5xx) is NOT caught -- it propagates out of run_once() entirely,
      so the new high-water mark is never saved this cycle. This kind IS
      plausibly transient (backend momentarily unreachable, mid-restart),
      so the safer default is retrying the WHOLE remaining batch next
      cycle rather than skipping past whatever failed. Safe to retry:
      POST /orders' dedup on (source_id, external_id) makes re-posting
      anything that already succeeded earlier in the same batch a no-op.
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
        failed = 0

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
            try:
                body = imap.fetch_plaintext_body(candidate.uid)
                # build_claims() re-runs classify() on the subject
                # internally -- redundant with the check above, but
                # negligible next to the body FETCH just made, and it
                # keeps build_claims() a self-contained, independently
                # testable unit (see tests/test_ingest.py) rather than one
                # that trusts a classification its caller computed
                # separately.
                claims = build_claims(candidate.subject, body, candidate.message_id, received_at)
            except Exception as exc:
                # THIS message's own problem (a MIME/encoding edge case
                # neither classify() nor a captured fixture predicted) --
                # not the batch's. highest_uid already advanced past it
                # above, so this exact message is never retried, but
                # nothing after it in this batch is blocked either. See
                # run_once()'s docstring for why this is caught here and
                # api.post_claim below deliberately isn't.
                print(f"(couldn't parse uid={candidate.uid} subject={candidate.subject!r}: {exc!r})", file=sys.stderr)
                failed += 1
                continue

            if not claims:
                skipped += 1
                continue
            for claim in claims:
                try:
                    api.post_claim(claim.to_payload(), source_id)
                    posted += 1
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500:
                        # A genuine problem with THIS claim's payload
                        # (a validation error, a bad enum value) -- the
                        # backend will reject it identically every time,
                        # so retrying is not "resilience," it's the exact
                        # same permanent-stall failure mode the parse-
                        # failure handling above exists to prevent, just
                        # one step later in the pipeline. Logged and
                        # skipped, not retried. A genuine network problem
                        # or backend-side error (httpx.RequestError, or a
                        # 5xx here) is NOT caught -- those propagate and
                        # abort the batch on purpose, see run_once()'s
                        # docstring.
                        print(
                            f"(claim rejected by backend, external_id={claim.external_id}: "
                            f"{exc.response.status_code} {exc.response.text[:300]!r})",
                            file=sys.stderr,
                        )
                        failed += 1
                        continue
                    raise

        state.save({"last_uid": highest_uid, "uidvalidity": current_validity})
        api.mark_source_synced()
        print(
            f"Processed {len(candidates)} message(s): {posted} claim(s) posted, "
            f"{skipped} not order-shaped mail, {failed} failed (unparseable or rejected by the backend)."
        )


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
