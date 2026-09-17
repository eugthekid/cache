"""
Fixtures are REAL plaintext bodies of Target shipping and cancellation
emails, captured verbatim during the 2026-09-17 sweep for the
cancel/tracking parser build -- tracking-link URLs stripped to a
"https://click.oe.target.com/?qs=redacted" placeholder (their real form is
a long per-message-unique encoded query string, not worth keeping
verbatim), everything else left exactly as sent. The 2022 fixture keeps
its redacted URL LINES in place, unlike every other fixture in this test
suite, specifically because this file's job is proving the parsers' own
URL-skip logic -- see the comment on that fixture below.

SHIPPED fixture: order 902003598796944 (thread 1a0ac89cbf63d317).
CANCELLED_FULL fixture: order 912003775371184 (thread 1a0a9847d357d70b).
CANCELLED_PARTIAL fixtures: TWO real orders, 4 years apart, to prove the
two different "Order #" markup shapes both parse -- 102002382211975
(2026, thread 19916e47671de66e, number directly after "Order #") and
9180113030448 (2022, thread 184398ef18c6cdde, "Order #" itself linked,
number on its own line below).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_target import parse_cancellation_order_number, parse_cancelled_lines, parse_shipped_line, parse_tracking_number

SHIPPED_BODY = """Order #902003598796944

 Eugene, we're getting ready to ship your order

Your shipping label has been created and we processed a payment of $43.53 for your items. You’ll find your tracking number below. Please allow 24 hours for tracking info to become available.

Shipping

 Delivers to: Eugene Seo, 5722 225th St, Flushing, NY, 11364

United Parcel Service Tracking # 1ZWY06570303836010

(Please allow 24 hours for tracking info to become available.)

Track status

 Pokémon Trading Card Game: 30th Celebration Poster Collection

 Qty: 2

Looking for your receipt?

Visit your
order details page and select receipts to view your receipt and more.
"""

# Second real SHIPPED-kind template -- classify()'s _TARGET_ARRIVES_SOON
# maps "arrives today/tomorrow" subjects to the SAME EmailKind.SHIPPED as
# the "getting ready to ship" template above, despite a visibly different
# body layout (different section markers on both sides of the product
# line). Order 902003598945564, thread 1a06c87fb24dc775.
ARRIVES_TODAY_BODY = """Order #902003598945564

 Eugene, your order arrives today!

 September 4

Good news — your order is out for delivery and will arrive today!

Visit order details for the latest updates.

 Arriving today

Pokémon Trading Card Game: Mega Evolution—Ascended Heroes Tin- Mega Meganium ex

 Qty: 2

Any issues with your order?

Fixing it is fast! Save time and fix it online. We’ll guide you through anything that’s not quite right.
"""

CANCELLED_FULL_BODY = """Replace Item

 Order #
912003775371184

 Your order has

been canceled

 Hi Eugene,

We wanted to let you know that order
#912003775371184 was canceled. We're sorry for the inconvenience. You haven't been charged for any items.
"""

# 2026 shape: the number sits directly after "Order #" on one line.
CANCELLED_PARTIAL_BODY_2026 = """Order #102002382211975

 Your items have
been canceled

 Hi Eugene,

As you requested, we have canceled the items below from your order #
View order details

 Canceled items

PS Placeholder 2025

 Qty: 2

  Shop your other favorites instead
"""

# 2022 shape: "Order #" is the hyperlink itself, with the actual URL line
# (redacted here, present in the real mail) between it and the number --
# this is what _CANCEL_ORDER_NUMBER_RE's optional URL-skip group exists
# for, and what the "Canceled items" section's own URL line before the
# product name exercises for parse_cancelled_lines's http-line skip. The
# 2026 fixture above never hits either skip branch (no link wraps "Order
# #" there, and its "Canceled items" section has no URL line either) --
# keeping this fixture's real link lines in, rather than stripping them
# to blank lines like every other test file's convention, is deliberate:
# stripping them would silently stop testing the one thing this fixture
# is for.
CANCELLED_PARTIAL_BODY_2022 = """Item Canceled Guest

 Order #

https://click.oe.target.com/?qs=redacted
9180113030448

 Your items have
been canceled

 Hi Eugene,

As you requested, we have canceled the items below from your order #
https://click.oe.target.com/?qs=redacted
9180113030448 .

Thank you for being our guest.
https://click.oe.target.com/?qs=redacted
View order details

Canceled items

https://click.oe.target.com/?qs=redacted

https://click.oe.target.com/?qs=redacted
Funko POP! TV: House of the Dragon- Caraxes (Dragon) (Target Exclusive)

 Qty: 2

https://click.oe.target.com/?qs=redacted
Help
"""

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


# --- shipped -----------------------------------------------------------
check("shipped: tracking number, carrier label not captured", parse_tracking_number(SHIPPED_BODY), "1ZWY06570303836010")

shipped_line = parse_shipped_line(SHIPPED_BODY)
check("shipped line found", shipped_line is not None, True)
if shipped_line:
    check("shipped line name", shipped_line.raw_product_text, "Pokémon Trading Card Game: 30th Celebration Poster Collection")
    check("shipped line qty", shipped_line.quantity, 2)
    check("shipped line carries no price field", hasattr(shipped_line, "unit_price"), False)

# Same function, the OTHER real SHIPPED-kind template -- proves the
# backward-walk-from-Qty generalizes across both body layouts rather than
# being tuned to one fixture.
arrives_line = parse_shipped_line(ARRIVES_TODAY_BODY)
check("arrives-today line found (2nd real SHIPPED template)", arrives_line is not None, True)
if arrives_line:
    check("arrives-today line name", arrives_line.raw_product_text, "Pokémon Trading Card Game: Mega Evolution—Ascended Heroes Tin- Mega Meganium ex")
    check("arrives-today line qty", arrives_line.quantity, 2)

# Constructed adversarial case, proving what the end-bound actually
# protects (see parse_shipped_line's docstring for what it does NOT):
# the real line's own "Qty:" is missing (a stand-in for a malformed row),
# but an upsell item AFTER "Looking for your receipt?" states its own
# Qty. An unbounded search would fall through to that and return the
# WRONG product; bounded, this correctly returns None instead of a
# confidently wrong guess.
SHIPPED_BODY_MISSING_REAL_QTY = """Order #902003598796944

 Eugene, we're getting ready to ship your order

United Parcel Service Tracking # 1ZWY06570303836010

Track status

 Pokémon Trading Card Game: 30th Celebration Poster Collection

Looking for your receipt?

Pokemon TCG Chinese 30th Ann...

 Qty: 1

Shop now
"""
check(
    "real line's Qty missing -> bound stops the fallthrough to the upsell's Qty (returns None, not a wrong guess)",
    parse_shipped_line(SHIPPED_BODY_MISSING_REAL_QTY),
    None,
)

# --- cancellation order number -------------------------------------------
check(
    "full-cancel body's split 'Order #' shape is NOT what this function targets (returns whatever it finds, unused by callers for this kind)",
    parse_cancellation_order_number(CANCELLED_FULL_BODY),
    "912003775371184",
)
check("partial-cancel 2026 shape: number directly after 'Order #'", parse_cancellation_order_number(CANCELLED_PARTIAL_BODY_2026), "102002382211975")
check("partial-cancel 2022 shape: 'Order #' linked, number on its own line", parse_cancellation_order_number(CANCELLED_PARTIAL_BODY_2022), "9180113030448")

# --- cancelled lines -------------------------------------------------------
lines_2026 = parse_cancelled_lines(CANCELLED_PARTIAL_BODY_2026)
check("2026: exactly 1 cancelled line", len(lines_2026), 1)
if lines_2026:
    check("2026 cancelled line name", lines_2026[0].raw_product_text, "PS Placeholder 2025")
    check("2026 cancelled line qty", lines_2026[0].quantity, 2)
    check("2026 cancelled line carries no price field", hasattr(lines_2026[0], "unit_price"), False)

lines_2022 = parse_cancelled_lines(CANCELLED_PARTIAL_BODY_2022)
check("2022: exactly 1 cancelled line (4-year-old template, same shape)", len(lines_2022), 1)
if lines_2022:
    check("2022 cancelled line name", lines_2022[0].raw_product_text, "Funko POP! TV: House of the Dragon- Caraxes (Dragon) (Target Exclusive)")
    check("2022 cancelled line qty", lines_2022[0].quantity, 2)

# --- absent-marker cases ------------------------------------------------
check("tracking number absent -> None", parse_tracking_number("no tracking info here"), None)
check("cancellation order number absent -> None", parse_cancellation_order_number("nothing relevant here"), None)
check("cancelled lines: no 'Canceled items' marker -> []", parse_cancelled_lines("nothing relevant here"), [])
check("shipped line: no 'Qty:' at all -> None", parse_shipped_line("nothing relevant here"), None)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
