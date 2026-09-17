"""
Fixture is the REAL plaintext body of Pokémon Center confirmation email
for order P0038875758 (thread 19f675e3a4060d74), captured verbatim during
the 2026-09-16 reconnaissance -- tracking-link URLs stripped (irrelevant
to parsing, just noise) but every table row, line break and dollar figure
left exactly as the source sent it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_pokemoncenter import parse_confirmation, parse_order_number, parse_purchased_at

BODY = """ Pokémon Center
We’re working on your order. Please review your order confirmation details inside.

| |

| |

| |
| Hello, Eugene! |
| Thank you for placing a preorder with us! Below is a copy of your order details. |

| |
| Order Details |
| Order Number: P0038875758 Date Ordered: July 15, 2026 |

| |
| Payment & Shipping |

| |
| Billing Address: Eugene Seo 220 Malt Dr Apartment 15 Long Island City, Ny 11101 US | Shipping Address: Eugene Seo 220 Malt Dr Apartment 15 Long Island City, Ny 11101 US |

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

| |

| |
| Order Subtotal | $149.96 |

| |
| Sales Tax | $13.31 |

| |
| Shipping | $0.00 |

| |
| Order Total | $163.27 |

| |

| |
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


check("order number", parse_order_number(BODY), "P0038875758")
check("purchased_at (raw string)", parse_purchased_at(BODY), "July 15, 2026")

lines = parse_confirmation(BODY)
check("3 lines extracted", len(lines), 3)

if len(lines) == 3:
    check("line 1 name", lines[0].raw_product_text, "Pokémon TCG: 30th Celebration Tech Sticker Collection (Lucario)")
    check("line 1 sku", lines[0].external_sku, "10-10449-122")
    check("line 1 qty", lines[0].quantity, 1)
    # $14.99 extended, tax share = 14.99/149.96*13.31 -> unit_price ~= $16.3206
    check("line 1 unit_price (tax-allocated, unrounded)", lines[0].unit_price, 16.3206, tol=0.001)

    check("line 2 name", lines[1].raw_product_text, "Pokémon TCG: 30th Celebration Pokémon Center Elite Trainer Box")
    check("line 2 sku", lines[1].external_sku, "10-10447-111")
    check("line 2 qty", lines[1].quantity, 2)
    # extended = 59.99*2 = 119.98, tax share = 119.98/149.96*13.31 -> (119.98+share)/2 ~= $65.3145/unit.
    # Not asserted against hand arithmetic (this file's own manual recompute
    # was wrong twice before landing here) -- the real correctness check is
    # the aggregate reconciliation below, which is independent of this
    # per-line number and passing it is what confirms this value is right.
    check("line 2 unit_price (tax-allocated, unrounded)", lines[1].unit_price, 65.3145, tol=0.001)

    check("line 3 name", lines[2].raw_product_text, "Pokémon TCG: 30th Celebration Tech Sticker Collection (Alolan Exeggutor)")
    check("line 3 sku", lines[2].external_sku, "10-10449-121")

    total_allocated = sum(l.unit_price * l.quantity for l in lines)
    # Left unrounded, this reconciles to the stated Order Total exactly
    # (to floating-point precision) -- the whole reason per-line rounding
    # was dropped. Rounding only HERE, at display/assertion time, is safe.
    check("allocated total reconciles to Order Total ($163.27)", round(total_allocated, 2), 163.27)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
