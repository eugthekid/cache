"""
Second real Target confirmation, order 912002032160334 (thread
1937bfe249810a76) -- chosen specifically because it has a real Target
Circle Card discount, which the first fixture (912003448396552) didn't
exercise. Body captured verbatim, tracking-link URLs stripped.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_target import parse_confirmation, parse_order_number, parse_purchased_at

BODY = """Order #912002032160334

 Thanks for your order, Eugene!

 Placed November 30, 2024

 Now just sit back while we get to work. We’ll reach out soon to let you know your order has shipped.

 Order total
$248.19

 You saved

 $12.00

Visit order details

Shipping

 Delivers to:
Eugene Seo, 5306 217th St, Oakdale Gdns, NY 11364-1416

Taylor Swift - The Tortured Poets Department: The Anthology (Target Exclusive, Vinyl)

 Qty: 4

 $59.99 / ea

 Arriving by Tue, Dec 10

Rate & review

Rate your recent purchases.

Write a review

Order Summary

Subtotal (4 items)

$239.96

 Discounts

 Target Circle Card 5%

-$12.00

Delivery

Free

Estimated taxes

Based on 11364

$20.23

Total

 $248.19

 Target Circle Debit Card *5806

$248.19

Need to make changes? Act fast.

We process orders quickly, so you’ll want to visit your
order details page as soon as possible.

 Take another look:

$54.99 - $84.99

DualSense Wireless Controller for PlayStation 5

Shop now

$29.99

Tile Sticker (2022)

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


check("order number", parse_order_number(BODY), "912002032160334")
check("purchased_at", parse_purchased_at(BODY), "November 30, 2024")

lines = parse_confirmation(BODY)
check("exactly 1 line", len(lines), 1)

if len(lines) == 1:
    line = lines[0]
    check("product name", line.raw_product_text,
          "Taylor Swift - The Tortured Poets Department: The Anthology (Target Exclusive, Vinyl)")
    check("quantity", line.quantity, 4)
    # $59.99*4 = $239.96 extended, +$20.23 tax, -$12.00 discount = $248.19, /4 = $62.0475/unit
    check("unit_price (tax+discount-inclusive)", line.unit_price, 62.0475, tol=0.001)
    total_allocated = line.unit_price * line.quantity
    check("allocated total reconciles to Order total ($248.19)", round(total_allocated, 2), 248.19)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
