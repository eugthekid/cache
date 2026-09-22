"""
Exercises ingest.build_claims() end-to-end -- subject + body in, Claim
list out -- against the same real fixtures the individual parser tests
already use (copied verbatim from those files; see each one's own
docstring for thread/order provenance). No live mailbox needed: this is
the whole point of keeping ingest.py pure I/O-free.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.classify import EmailKind, Retailer
from app.email_ingest.ingest import build_claims, parse_email_date

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


# A real Date header shape (Gmail's own format), reused across fixtures --
# the exact value doesn't matter to any check below except that it parses
# and shows up as occurred_at.
DATE_HEADER = "Wed, 15 Jul 2026 09:12:00 +0000"
EXPECTED_OCCURRED_AT = parse_email_date(DATE_HEADER).isoformat()


# --- Pokemon Center confirmation (order P0038875758, thread 19f675e3a4060d74) ---
PC_CONFIRM_SUBJECT = "Thank you for shopping at PokemonCenter.com!"
PC_CONFIRM_BODY = """ Pokémon Center
We’re working on your order. Please review your order confirmation details inside.

| |
| Order Details |
| Order Number: P0038875758 Date Ordered: July 15, 2026 |

| |
| Order Summary |

| |
| Pokémon TCG: 30th Celebration Tech Sticker Collection (Lucario) |
| SKU #: 10-10449-122 Qty: 1 Price: $14.99 |

| |
| |

| |
| Pokémon TCG: 30th Celebration Pokémon Center Elite Trainer Box |
| SKU #: 10-10447-111 Qty: 2 Price: $59.99 |

| |
| |

| |
| Pokémon TCG: 30th Celebration Tech Sticker Collection (Alolan Exeggutor) |
| SKU #: 10-10449-121 Qty: 1 Price: $14.99 |

| |

| |
| Order Subtotal | $149.96 |

| |
| Sales Tax | $13.31 |

| |
| Shipping | $0.00 |

| |
| Order Total | $163.27 |
"""

claims = build_claims(PC_CONFIRM_SUBJECT, PC_CONFIRM_BODY, "msg-pc-confirm@mail", parse_email_date(DATE_HEADER))
check("PC confirmation: 3 claims", len(claims), 3)
if len(claims) == 3:
    check("PC confirmation claim 0 external_id", claims[0].external_id, "msg-pc-confirm@mail:confirm:0")
    check("PC confirmation claim 0 status", claims[0].status, "success")
    check("PC confirmation claim 0 site", claims[0].site, "pokemoncenter.com")
    check("PC confirmation claim 0 order_number", claims[0].order_number, "P0038875758")
    check("PC confirmation claim 0 sku", claims[0].external_sku, "10-10449-122")
    check("PC confirmation claim 0 purchased_at", claims[0].purchased_at, "2026-07-15T00:00:00")
    check("PC confirmation claim 0 occurred_at (from Date header)", claims[0].occurred_at, EXPECTED_OCCURRED_AT)
    check("PC confirmation claim 1 external_id (distinct index)", claims[1].external_id, "msg-pc-confirm@mail:confirm:1")
    check("PC confirmation claim 2 unit_price is a real tax-allocated number", round(claims[2].unit_price, 2), 16.32)
    # This trimmed fixture never had a "Shipping Address:" block to begin
    # with -- see test_parse_pokemoncenter.py and
    # test_parse_pokemoncenter_ship_to_address.py for the extraction
    # itself; this just confirms the wiring doesn't crash or invent one
    # when the marker is absent.
    check("PC confirmation claim 0 ship_to_address (absent from this fixture)", claims[0].ship_to_address, None)

# --- Pokemon Center shipped (order P0038927021, thread 1a0a5ce2cc85a81b) ---
PC_SHIP_SUBJECT = "Your Pokémon Center order is on its way!"
PC_SHIP_BODY = """ Pokémon Center
Hooray! Find out when your order will arrive.

| |
| Hello, Eugene! |
| Your package has shipped! Tracking Number: 876939896536[]() Payment will be taken from your chosen payment method. |

| |
| Order Details |
| Order Subtotal: $149.96 Order Number: P0038927021 Fulfillment ID: 24493675 Date Ordered: July 15, 2026 |

| |
| Order Summary |

| |
| Pokémon TCG: 30th Celebration Tech Sticker Collection (Alolan Exeggutor) |
| SKU # : 10-10449-121 Qty : 1 |

| |
| |

| |
| Pokémon TCG: 30th Celebration Tech Sticker Collection (Lucario) |
| SKU # : 10-10449-122 Qty : 1 |

| |
"""

ship_claims = build_claims(PC_SHIP_SUBJECT, PC_SHIP_BODY, "msg-pc-ship@mail", parse_email_date(DATE_HEADER))
check("PC shipped: 2 claims", len(ship_claims), 2)
if len(ship_claims) == 2:
    check("PC shipped claim 0 external_id", ship_claims[0].external_id, "msg-pc-ship@mail:ship:0")
    check("PC shipped claim 0 tracking_number", ship_claims[0].tracking_number, "876939896536")
    check("PC shipped claim 0 shipping_status", ship_claims[0].shipping_status, "in_transit")
    check("PC shipped claim 0 has no unit_price (unknown for a shipped line)", ship_claims[0].unit_price, None)

# Synthetic (not a real fixture): a SHIPPED body with a tracking number
# but no "Order Summary" section at all, simulating a template hiccup
# where parse_shipped_lines() finds no lines. The tracking number must
# still make it out as one order-level claim, not get silently dropped --
# this is what ingest.py's fallback in the SHIPPED branch exists for.
PC_SHIP_NO_LINES_BODY = """ Pokémon Center
Your package has shipped! Tracking Number: 999888777[]()

Order Number: P0099999999 Date Ordered: July 15, 2026
"""
fallback_claims = build_claims(PC_SHIP_SUBJECT, PC_SHIP_NO_LINES_BODY, "msg-pc-ship-nolines@mail", parse_email_date(DATE_HEADER))
check("PC shipped, no lines parsed but tracking present: 1 order-level claim (not dropped)", len(fallback_claims), 1)
if len(fallback_claims) == 1:
    fc = fallback_claims[0]
    check("fallback claim external_id (no line index -- single order-level claim)", fc.external_id, "msg-pc-ship-nolines@mail:ship")
    check("fallback claim tracking_number", fc.tracking_number, "999888777")
    check("fallback claim shipping_status", fc.shipping_status, "in_transit")
    check("fallback claim carries no line signal (relies on matching.py's rule 5)", fc.raw_product_text, None)

# And the fully-degenerate case: no lines AND no tracking number either
# -> nothing to claim at all.
check(
    "PC shipped, nothing parseable at all -> []",
    build_claims(PC_SHIP_SUBJECT, " Pokémon Center\nnothing relevant here", "msg-pc-ship-empty@mail", parse_email_date(DATE_HEADER)),
    [],
)

# --- Pokemon Center cancelled (order P0038894998, thread 1a07c7bf674b6dee) ---
PC_CANCEL_SUBJECT = "Your order has been canceled"
PC_CANCEL_BODY = """ Pokémon Center
Please contact us with any questions or concerns.

| |
| Hello, Eugene, |
| We’re sorry that the below item(s) from your order couldn't be processed hence been canceled. |

| |
| Order Details |
| Order Number: P0038894998 Date Ordered: July 15, 2026 |

| |
| Order Summary |

| |
| Pokémon TCG: 30th Celebration Tech Sticker Collection (Alolan Exeggutor) |
| SKU #: 10-10449-121 Qty: 1 |

| |
"""

cancel_claims = build_claims(PC_CANCEL_SUBJECT, PC_CANCEL_BODY, "msg-pc-cancel@mail", parse_email_date(DATE_HEADER))
check("PC cancelled: 1 claim", len(cancel_claims), 1)
if len(cancel_claims) == 1:
    check("PC cancelled claim status", cancel_claims[0].status, "cancelled")
    check("PC cancelled claim sku", cancel_claims[0].external_sku, "10-10449-121")

# --- Target confirmation (order 912003448396552, thread 19e4e800e1e6f6c5) ---
TARGET_CONFIRM_SUBJECT = "Thanks for shopping with us! Here's your order #:912003448396552."
TARGET_CONFIRM_BODY = """Order #912003448396552

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

 Arrives Wed, Jun 3

Order Summary

Subtotal (2 items)

$119.98

Estimated taxes

Based on 11364

$10.65

Total

 $130.63

Need to make changes? Act fast.
"""

t_confirm_claims = build_claims(TARGET_CONFIRM_SUBJECT, TARGET_CONFIRM_BODY, "msg-t-confirm@mail", parse_email_date(DATE_HEADER))
check("Target confirmation: 1 claim", len(t_confirm_claims), 1)
if len(t_confirm_claims) == 1:
    c = t_confirm_claims[0]
    check("Target confirmation external_id (no numeric suffix -- single-claim event)", c.external_id, "msg-t-confirm@mail:confirm")
    check("Target confirmation order_number (from subject, not body)", c.order_number, "912003448396552")
    check("Target confirmation purchased_at", c.purchased_at, "2026-05-22T00:00:00")
    # Not hand-recomputed -- test_parse_target.py's own test already
    # verifies this figure (65.315, tol 0.001) reconciles to the stated
    # Order total; this just confirms ingest.py passes it through
    # unchanged.
    check("Target confirmation unit_price reconciles to Order total", round(c.unit_price * c.quantity, 2), 130.63)
    check("Target confirmation ship_to_address", c.ship_to_address, "Eugene Seo, 5306 217th Street, Oakland Gardens, NY 11364")

# --- Target shipped (order 902003598796944, thread 1a0ac89cbf63d317) ---
# Subject copied byte-for-byte from the real fetch, NO space before
# "are" -- this exact string is what caught classify.py's _TARGET_SHIPPED
# regex bug (it required a space no real subject actually has).
TARGET_SHIP_SUBJECT = "Get ready for something special! Items from order #902003598796944are about to ship."
TARGET_SHIP_BODY = """Order #902003598796944

 Eugene, we're getting ready to ship your order

Shipping

 Delivers to: Eugene Seo, 5722 225th St, Flushing, NY, 11364

United Parcel Service Tracking # 1ZWY06570303836010

(Please allow 24 hours for tracking info to become available.)

Track status

 Pokémon Trading Card Game: 30th Celebration Poster Collection

 Qty: 2

Looking for your receipt?
"""

t_ship_claims = build_claims(TARGET_SHIP_SUBJECT, TARGET_SHIP_BODY, "msg-t-ship@mail", parse_email_date(DATE_HEADER))
check("Target shipped: 1 claim", len(t_ship_claims), 1)
if len(t_ship_claims) == 1:
    c = t_ship_claims[0]
    check("Target shipped tracking_number", c.tracking_number, "1ZWY06570303836010")
    check("Target shipped shipping_status", c.shipping_status, "in_transit")
    check("Target shipped raw_product_text (gives match_line a signal)", c.raw_product_text, "Pokémon Trading Card Game: 30th Celebration Poster Collection")
    check("Target shipped order_number (from subject)", c.order_number, "902003598796944")

# --- Target full cancellation (order 912003775371184, thread 1a0a9847d357d70b) ---
TARGET_CANCEL_FULL_SUBJECT = "Sorry, we had to cancel order #912003775371184."
TARGET_CANCEL_FULL_BODY = """Replace Item

 Order #
912003775371184

 Your order has

been canceled

 Hi Eugene,

We wanted to let you know that order
#912003775371184 was canceled. We're sorry for the inconvenience. You haven't been charged for any items.
"""

t_cancel_full_claims = build_claims(TARGET_CANCEL_FULL_SUBJECT, TARGET_CANCEL_FULL_BODY, "msg-t-cancel-full@mail", parse_email_date(DATE_HEADER))
check("Target full cancel: 1 claim", len(t_cancel_full_claims), 1)
if len(t_cancel_full_claims) == 1:
    c = t_cancel_full_claims[0]
    check("Target full cancel status", c.status, "cancelled")
    check("Target full cancel order_number (subject-derived, the only reliable source)", c.order_number, "912003775371184")
    check("Target full cancel carries no line data at all (relies on matching.py's rule 5)", c.raw_product_text, None)
    check("Target full cancel external_id (single-claim event)", c.external_id, "msg-t-cancel-full@mail:cancel")

# --- Target partial cancellation (order 102002382211975, thread 19916e47671de66e) ---
TARGET_CANCEL_PARTIAL_SUBJECT = "You've successfully canceled items from your order ending in 1975."
TARGET_CANCEL_PARTIAL_BODY = """Order #102002382211975

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

# --- Target arrived (order 912003448396552, trimmed from real mail, uid 281228) ---
TARGET_ARRIVED_SUBJECT = "Items have arrived from order #912003448396552!"
TARGET_ARRIVED_BODY = """Order #912003448396552

 Eugene, items from your order have arrived

 Delivered June 1, 2026

 Time to kick up your feet, settle in and enjoy your new stuff.

Pokémon Trading Card Game: Mega Evolution Chaos Rising Elite Trainer Box

 Qty: 2

Delivered on Mon, Jun 1, 2026
"""

t_arrived_claims = build_claims(TARGET_ARRIVED_SUBJECT, TARGET_ARRIVED_BODY, "msg-t-arrived@mail", parse_email_date(DATE_HEADER))
check("Target arrived: 1 claim", len(t_arrived_claims), 1)
if len(t_arrived_claims) == 1:
    c = t_arrived_claims[0]
    check("Target arrived status (a true assertion, sticky-cancelled protects the rest)", c.status, "success")
    check("Target arrived order_number (from subject)", c.order_number, "912003448396552")
    check("Target arrived shipping_status", c.shipping_status, "delivered")
    check("Target arrived tracking_detail carries the retailer's own delivered date", c.tracking_detail, "Delivered June 1, 2026")
    check("Target arrived carries no line data (relies on matching.py's rule 5, same as full cancellation)", c.raw_product_text, None)
    check("Target arrived external_id (single-claim event)", c.external_id, "msg-t-arrived@mail:arrived")

# --- Target cancellation, THIRD subject shape (order 912003760839485,
# found live 2026-09-21 cross-checking against an independent Gmail
# read): full order number in the subject like CANCELLED_FULL, but a
# "Canceled items" + Qty body like CANCELLED_PARTIAL. ---
TARGET_CANCEL_ITEMS_SUBJECT = "Sorry we had to cancel items in order #912003760839485."
TARGET_CANCEL_ITEMS_BODY = """Order #912003760839485

 Sorry we had
to cancel your items

 Hi Eugene,

Thanks so much for placing your recent order #
912003760839485 . We went to grab the items listed below, but it looks like someone snagged the last of them.

 Canceled items

Pokémon Trading Card Game: 30th Celebration Sylveon ex Box

 Qty: 2
"""

t_cancel_items_claims = build_claims(TARGET_CANCEL_ITEMS_SUBJECT, TARGET_CANCEL_ITEMS_BODY, "msg-t-cancel-items@mail", parse_email_date(DATE_HEADER))
check("Target cancel-items (3rd subject shape): 1 claim", len(t_cancel_items_claims), 1)
if len(t_cancel_items_claims) == 1:
    c = t_cancel_items_claims[0]
    check("Target cancel-items status", c.status, "cancelled")
    check("Target cancel-items order_number comes from the SUBJECT, not re-parsed from the body", c.order_number, "912003760839485")
    check("Target cancel-items product name", c.raw_product_text, "Pokémon Trading Card Game: 30th Celebration Sylveon ex Box")
    check("Target cancel-items quantity", c.quantity, 2)

t_cancel_partial_claims = build_claims(
    TARGET_CANCEL_PARTIAL_SUBJECT, TARGET_CANCEL_PARTIAL_BODY, "msg-t-cancel-partial@mail", parse_email_date(DATE_HEADER)
)
check("Target partial cancel: 1 claim", len(t_cancel_partial_claims), 1)
if len(t_cancel_partial_claims) == 1:
    c = t_cancel_partial_claims[0]
    check("Target partial cancel status", c.status, "cancelled")
    check("Target partial cancel order_number (body-derived -- subject only has last 4 digits)", c.order_number, "102002382211975")
    check("Target partial cancel raw_product_text", c.raw_product_text, "PS Placeholder 2025")
    check("Target partial cancel quantity", c.quantity, 2)

# Same body, but with the "Order #NNN" heading stripped out entirely --
# simulates parse_cancellation_order_number() failing to find a number
# (a future template surprise). Without the order_number guard, this used
# to still build and return a claim with order_number=None: since
# app/matching.find_cart requires one, that claim could only ever create
# an ORPHANED "cancelled" order with no line back to the real cart it was
# meant to cancel, worse than surfacing nothing.
TARGET_CANCEL_PARTIAL_BODY_NO_ORDER_NUMBER = TARGET_CANCEL_PARTIAL_BODY.replace("Order #102002382211975\n\n", "")
check(
    "Target partial cancel with no parseable order_number -> [] (never an orphaned claim)",
    build_claims(TARGET_CANCEL_PARTIAL_SUBJECT, TARGET_CANCEL_PARTIAL_BODY_NO_ORDER_NUMBER, "msg-t-cancel-partial-noorder@mail", parse_email_date(DATE_HEADER)),
    [],
)

# --- not built / not recognized -------------------------------------------
check("unrecognized subject -> no claims", build_claims("50% off everything this weekend!", "body", "msg-x@mail", None), [])
check(
    "Walmart subject -> no claims (no parser built yet)",
    build_claims("Thanks for your delivery order, Eugene", "body", "msg-w@mail", None),
    [],
)
check(
    "malformed Date header doesn't crash email parsing",
    parse_email_date("not a real date"),
    None,
)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
