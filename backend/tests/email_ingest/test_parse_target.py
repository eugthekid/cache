"""
Fixture is the REAL plaintext body of Target's confirmation email for
order 912003448396552 (thread 19e4e800e1e6f6c5), captured verbatim during
the 2026-09-16 reconnaissance -- tracking-link URLs stripped, every other
line (including the "Take another look" upsell block, deliberately kept
in to prove the parser skips it) left exactly as sent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_target import parse_confirmation, parse_order_number, parse_purchased_at, parse_ship_to_address

BODY = """Order #912003448396552

 Thanks for your order, Eugene!

 Placed May 22, 2026

 Now just sit back while we get to work. We’ll send you
an email when tracking info is available.

 Order total
$130.63

Visit order details

Shipping

 Delivers to:
Eugene Seo, 5306 217th Street, Oakland Gardens, NY 11364

Pokémon Trading Card Game: Mega Evolution Chaos Rising Elite Trainer Box

 Qty: 2

 $59.99 / ea

 Arrives Wed, Jun 3

 Rate & review

 Rate your recent purchases.

Write a review

Order Summary

Subtotal (2 items)

$119.98

Delivery

Free

Estimated taxes

Based on 11364

$10.65

Total

 $130.63

 Visa *5193

$130.63

Need to make changes? Act fast.

We process orders quickly, so you’ll want to visit your
order details page as soon as possible.

 Take another look:

$39.99

Pokemon TCG Chinese 30th Ann...

Shop now

$329.00 - $499.00

Oura Ring 4

Shop now
"""

passed = failed = 0


def check(label, got, want, tol=None):
    global passed, failed
    ok = abs(got - want) < tol if tol is not None else got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        expected: {want!r}")
        print(f"        got:      {got!r}")
    if ok:
        passed += 1
    else:
        failed += 1


check("order number", parse_order_number(BODY), "912003448396552")
check("purchased_at (raw string)", parse_purchased_at(BODY), "May 22, 2026")

lines = parse_confirmation(BODY)
check("exactly 1 line (Target never has more, per docstring)", len(lines), 1)

if len(lines) == 1:
    line = lines[0]
    check(
        "product name -- NOT the upsell block's 'Pokemon TCG Chinese 30th Ann...'",
        line.raw_product_text,
        "Pokémon Trading Card Game: Mega Evolution Chaos Rising Elite Trainer Box",
    )
    check("quantity", line.quantity, 2)
    # $59.99/ea * 2 = $119.98 extended, +$10.65 tax, /2 units = $65.315/unit
    check("unit_price (tax-inclusive)", line.unit_price, 65.315, tol=0.001)
    total_allocated = line.unit_price * line.quantity
    check("allocated total reconciles to Order total ($130.63)", round(total_allocated, 2), 130.63)

check("ship_to_address", parse_ship_to_address(BODY), "Eugene Seo, 5306 217th Street, Oakland Gardens, NY 11364")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
