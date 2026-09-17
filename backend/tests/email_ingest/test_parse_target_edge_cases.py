"""
Adversarial cases the two real fixtures didn't happen to exercise --
constructed to prove specific fixes actually work, not just that real
mail parses. Each is clearly marked as constructed, not captured.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_target import parse_confirmation

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


# Based on the real 912003448396552 fixture, with one CONSTRUCTED addition:
# a "-$15.00 off" badge in the upsell block, which neither real sample had
# but is a plausible future Target promo pattern.
BODY_WITH_UPSELL_DISCOUNT_BADGE = """Order #912003448396552

 Thanks for your order, Eugene!

 Placed May 22, 2026

 Order total
$130.63

Shipping

 Delivers to:
Eugene Seo, 5306 217th Street, Oakland Gardens, NY 11364

Pokémon Trading Card Game: Mega Evolution Chaos Rising Elite Trainer Box

 Qty: 2

 $59.99 / ea

Rate & review

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

-$15.00 off select toys!

$39.99

Pokemon TCG Chinese 30th Ann...

Shop now
"""

lines = parse_confirmation(BODY_WITH_UPSELL_DISCOUNT_BADGE)
check("upsell '-$15.00' badge does NOT bleed into the discount total", len(lines), 1)
if lines:
    # If the bug were still present, the $15 would have been subtracted:
    # (119.98+10.65-15.00)/2 = 57.815 instead of the correct 65.315.
    check("unit_price unaffected by the upsell badge", round(lines[0].unit_price, 4), 65.315)


# Genuinely malformed: Qty/price found, but the stated Subtotal doesn't
# match the extended price at all -- simulating either a real multi-line
# cart Target has never sent before, or the name/qty/price walk landing on
# the wrong row. The safety net (added during review) must refuse to
# guess rather than silently return a wrong number.
BODY_SUBTOTAL_MISMATCH = """Order #912003448396552

 Thanks for your order, Eugene!

 Order total
$130.63

Shipping

 Delivers to: somewhere

Some Product

 Qty: 2

 $59.99 / ea

Order Summary

Subtotal (2 items)

$999.99

Total

 $130.63
"""

check(
    "subtotal mismatch -> refuses to guess (returns [])",
    parse_confirmation(BODY_SUBTOTAL_MISMATCH),
    [],
)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
