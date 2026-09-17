"""
Fixtures are REAL plaintext bodies of Pokémon Center shipping and
cancellation emails, captured verbatim during the 2026-09-17 sweep for the
cancel/tracking parser build -- tracking-link URLs stripped, everything
else (including the markdown-link marker directly glued to the tracking
number, with no space) left exactly as sent.

SHIPPED fixture: order P0038927021 (thread 1a0a5ce2cc85a81b).
CANCELLED fixture: order P0038894998 (thread 1a07c7bf674b6dee) -- a SECOND
real cancellation, order P0038918210 (thread 1a07c7bf20af1f52), has the
identical 3-line shape, so it isn't duplicated here as its own fixture.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_pokemoncenter import parse_cancelled_lines, parse_order_number, parse_shipped_lines, parse_tracking_number

SHIPPED_BODY = """ Pokémon Center
Hooray! Find out when your order will arrive.

| |
| Hello, Eugene! |
| Your package has shipped! Estimated delivery is 3-6 business days however where possible we’ll try to deliver your order sooner. Please allow up to 8 business days before contacting us regarding your order. Tracking Number: 876939896536[]() Payment will be taken from your chosen payment method. In the meantime, please refer to our FAQ section to find answers to any questions you may have. Sincerely, Pokémon Center |

| |
| Order Details |
| Order Subtotal: $149.96 Order Number: P0038927021 Fulfillment ID: 24493675 Date Ordered: July 15, 2026 |

| |
| Shipping Details |
| Shipping Address: Eugene Seo 220-73A 67th Ave 2nd Flr Oakland Gardens, NY 11364 US |

| |
| Order Summary |

| |
| Pokémon TCG: 30th Celebration Tech Sticker Collection (Alolan Exeggutor) |
| SKU # : 10-10449-121 Qty : 1 |

| |
| |

| |
| Pokémon TCG: 30th Celebration Pokémon Center Elite Trainer Box |
| SKU # : 10-10447-111 Qty : 2 |

| |
| |

| |
| Pokémon TCG: 30th Celebration Tech Sticker Collection (Lucario) |
| SKU # : 10-10449-122 Qty : 1 |

| |

| |
"""

CANCELLED_BODY = """ Pokémon Center
Please contact us with any questions or concerns.

| |
| Hello, Eugene, |
| We’re sorry that the below item(s) from your order couldn't be processed hence been canceled. You will not be charged for the canceled item(s) in your order, though you may see a temporary authorization on funds in your bank account. Please note that this authorization will be released by your bank according to their policies. The rest of the items (if any) in your order will be processed. We once again apologise for any inconvenience this may cause you. Please refer to our FAQ section for any questions you may have. Sincerely, The Pokémon Center Team |

| |
| Order Details |
| Order Number: P0038894998 Date Ordered: July 15, 2026 |

| |
| Order Summary |

| |
| Pokémon TCG: 30th Celebration Tech Sticker Collection (Alolan Exeggutor) |
| SKU #: 10-10449-121 Qty: 1 |

| |
| |

| |
| Pokémon TCG: 30th Celebration Tech Sticker Collection (Lucario) |
| SKU #: 10-10449-122 Qty: 1 |

| |
| |

| |
| Pokémon TCG: 30th Celebration Pokémon Center Elite Trainer Box |
| SKU #: 10-10447-111 Qty: 2 |

| |

| |
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
check("shipped: order number (same field as confirmation)", parse_order_number(SHIPPED_BODY), "P0038927021")
check(
    "shipped: tracking number stops at the glued-on link marker",
    parse_tracking_number(SHIPPED_BODY),
    "876939896536",
)

shipped_lines = parse_shipped_lines(SHIPPED_BODY)
check("shipped: 3 lines extracted (same row shape as cancellation, extra space around '#')", len(shipped_lines), 3)
if len(shipped_lines) == 3:
    check("shipped line 1 sku", shipped_lines[0].external_sku, "10-10449-121")
    check("shipped line 2 sku, qty 2", (shipped_lines[1].external_sku, shipped_lines[1].quantity), ("10-10447-111", 2))
    check("shipped line 3 sku", shipped_lines[2].external_sku, "10-10449-122")

# --- cancelled -----------------------------------------------------------
cancelled = parse_cancelled_lines(CANCELLED_BODY)
check("cancelled: 3 lines extracted (this order's full cart)", len(cancelled), 3)

if len(cancelled) == 3:
    check("cancelled line 1 name", cancelled[0].raw_product_text, "Pokémon TCG: 30th Celebration Tech Sticker Collection (Alolan Exeggutor)")
    check("cancelled line 1 sku", cancelled[0].external_sku, "10-10449-121")
    check("cancelled line 1 qty", cancelled[0].quantity, 1)

    check("cancelled line 2 sku", cancelled[1].external_sku, "10-10449-122")

    check("cancelled line 3 sku", cancelled[2].external_sku, "10-10447-111")
    check("cancelled line 3 qty", cancelled[2].quantity, 2)

# No unit_price attribute at all -- CancelledLine deliberately doesn't
# carry one (see module docstring). hasattr, not a bare access, so this
# fails with a clear message rather than an AttributeError traceback if
# the dataclass ever changes shape.
check("cancelled lines carry no price field", hasattr(cancelled[0], "unit_price") if cancelled else None, False)

# --- absent-marker cases ------------------------------------------------
check("tracking number absent -> None", parse_tracking_number("no tracking info here"), None)
check("cancelled lines: no Order Summary marker -> []", parse_cancelled_lines("nothing relevant here"), [])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
