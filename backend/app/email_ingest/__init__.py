"""
app/email_ingest/
------------------
Email order ingestion, living INSIDE the backend process rather than as a
separate script/service -- unlike the Discord bot, email has no reason to
be a separate process: it holds no persistent connection that needs to
outlive Cache being open (a message sitting in an inbox is still there
whenever the backend next polls it), so there is nothing a second process
buys here except the exact setup friction ("install a background
service") the user explicitly asked to avoid.

classify.py, parse_pokemoncenter.py, parse_target.py, html_to_text.py and
ingest.py are UNCHANGED in substance from their original home at
email_ingest/src/ (moved wholesale, 2026-09-17, imports adjusted to be
package-relative) -- 144 tests' worth of real-mail-verified parsing logic,
none of it rewritten. imap_client.py is adapted to take credentials as
constructor arguments instead of reading a module-level dotenv config,
since this now runs inside the backend's own process (which already has
its own settings/credential story via app/routers/email_account.py) --
see that file's own docstring for what changed and why.

app/email_poller.py (a sibling of this package, not inside it) is the
part that actually runs a loop and talks to the database -- everything
in THIS package stays pure (no I/O, no DB), same discipline the original
email_ingest/ project held to, which is what let it be tested against
captured fixtures with no live mailbox in the first place.
"""
