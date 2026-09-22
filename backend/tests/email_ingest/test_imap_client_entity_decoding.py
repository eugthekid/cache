"""
Pins fetch_plaintext_body()'s html.unescape() fix (2026-09-18), found via
a real live message (uid 286888, a Target confirmation): the message is
multipart/alternative, and fetch_plaintext_body correctly prefers its
native text/plain part -- but that part's own text, as TARGET SENT IT,
contains literal undecoded numeric HTML character references
("Pok&#233;mon", "Mega Evolution&#8212;Ascended...") instead of real
characters. Nothing downstream ever unescaped them, so the raw entities
ended up stored as the order's raw_product_text, which normalized to a
DIFFERENT key than the correctly-accented text Discord reported for the
same physical item -- silently splitting one product into two.

This fixture reproduces that exact MIME shape (multipart/alternative,
entities baked into the text/plain part) rather than testing
html.unescape() in isolation, so a regression in EITHER the MIME
part-selection logic or the missing unescape call would be caught.
"""
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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


msg = MIMEMultipart("alternative")
msg["Subject"] = "Thanks for shopping with us! Here's your order #:902003598780787."
plain_body = (
    "Pok&#233;mon Trading Card Game: Mega Evolution&#8212;Ascended Heroes Tin- Mega Meganium ex\r\n"
)
html_body = "<html><body><p>irrelevant for this test</p></body></html>"
msg.attach(MIMEText(plain_body, "plain"))
msg.attach(MIMEText(html_body, "html"))
raw_bytes = msg.as_bytes()

client = ImapClient("addr@example.com", "app-password")
client._conn = MagicMock()
client._conn.uid.return_value = ("OK", [(b"1 (UID 286888 BODY[] {123}", raw_bytes)])

body = client.fetch_plaintext_body(286888)
check("real accented character decoded, not left as a literal entity", "é" in body, True)
check("em dash decoded, not left as a literal entity", "—" in body, True)
check("no raw numeric character reference survives", "&#" in body, False)
check("exact expected product name", "Pokémon Trading Card Game: Mega Evolution—Ascended Heroes Tin- Mega Meganium ex" in body, True)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
