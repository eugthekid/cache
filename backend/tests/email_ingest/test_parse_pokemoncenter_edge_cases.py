"""
Adversarial case the real fixture didn't exercise: a line whose SKU row
doesn't match _SKU_ROW_RE (simulating a template tweak or a malformed
row), silently dropping it from raw_lines. Before the subtotal
cross-check was added during review, this would have allocated the
FULL cart tax across only the 2 lines that did parse -- overstating both
of their unit_price -- with nothing to signal the third line went
missing. Based on the real P0038875758 fixture with SKU deliberately
mangled on the third line ("SKU#10-10449-121" -- missing the required
"#:" separator).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_pokemoncenter import parse_confirmation

BODY_MISSING_LINE = """ Pokémon Center

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
| SKU#10-10449-121 Qty: 1 Price: $14.99 |

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


check(
    "3rd line's mangled SKU row -> whole order refuses to guess (returns [])",
    parse_confirmation(BODY_MISSING_LINE),
    [],
)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
