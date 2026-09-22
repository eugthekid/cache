"""
Fixture trimmed from a REAL Pokémon Center confirmation email (uid
278325), captured live 2026-09-19 while building shipping-address
extraction: PC's "Shipping Address:" block renders across several
indented lines here, not the single "| Shipping Address: ... |" row
test_parse_pokemoncenter.py's older fixture uses -- same drift pattern
already seen in the cancellation template (see
test_parse_pokemoncenter_nested_table_cancel.py). parse_ship_to_address
has to handle both shapes; this pins the multi-line one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_pokemoncenter import parse_ship_to_address

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


BODY = """            | Billing Address:
                            Eugene Seo
         5306 217th Street
         Oakland Gardens, Ny 11364
         US | Shipping Address:
                           Eugene Seo
         5306 217th Street
         Oakland Gardens, Ny 11364
         US |

                        | Order Summary |
"""

check(
    "multi-line address collapsed to one readable line",
    parse_ship_to_address(BODY),
    "Eugene Seo 5306 217th Street Oakland Gardens, Ny 11364 US",
)
check("no marker -> None", parse_ship_to_address("no address here"), None)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
