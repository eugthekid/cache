"""
Fixture trimmed from a REAL Target "items have arrived" email (order
912003448396552, uid 281228), captured live 2026-09-19. The body carries
TWO "Delivered ..." occurrences: a clean one near the top ("Delivered
June 1, 2026") and a second, differently-formatted one next to the line
item itself ("Delivered on Mon, Jun 1, 2026"). parse_delivered_at must
land on the FIRST, clean one -- verified against 4 real ARRIVED emails
spanning May-July 2026, all the same shape.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_target import parse_delivered_at

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


BODY = """Order #912003448396552

 Eugene, items from your order have arrived

 Delivered June 1, 2026

 Time to kick up your feet, settle in and enjoy your new stuff.

Visit order details

Pokémon Trading Card Game: Mega Evolution Chaos Rising Elite Trainer Box

 Qty: 2

Delivered on Mon, Jun 1, 2026

 Rate & review

 Take another look:

$129.99

Pokémon Starter Pullover Jac...
"""

check("delivered_at -- the first, clean occurrence", parse_delivered_at(BODY), "June 1, 2026")
check("no marker -> None", parse_delivered_at("nothing here"), None)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
