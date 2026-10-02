"""
Fixture trimmed from a REAL Pokémon Center SHIPPED email (order
P0039903378, uid 289752), captured live 2026-10-01 while investigating why
16 shipped orders sat in Cache's "Unmatched" bucket despite PC's own email
plainly naming the product (user screenshotted one and asked why Cache
didn't use it).

ROOT CAUSE: this template's SKU/Qty row is split across FOUR lines, not
the one-line (test_parse_pokemoncenter.py) or two-line
(test_parse_pokemoncenter_nested_table_cancel.py) shapes already handled:
"SKU #" alone, ": 10-10451-115" alone, "Qty" alone, ": 3" alone. Neither
existing regex matches any of those four lines, so parse_shipped_lines
returned [] and ingest.py's SHIPPED branch fell back to its zero-signal,
order-level tracking claim -- tracking number captured, product lost.
This is why the module docstring's claim that order P0038927021 "verified"
the two-line shape was wrong: that order is this same four-line shape: see
[[cache-name-affinity-matching-fix-2026-09-25]]-era memory for the
unmatched-items investigation this bug was found under.

Kept UNTRIMMED exactly as received, including PC's usual 2-3 mangled
re-renderings of each row at shallower table nesting (a value line fused
to the next copy's "SKU #" across a "|", e.g. ": 1 | SKU #") -- this is
what proves the fail-closed discipline (anchor the label/value lines so a
mangled repeat can't match) actually holds against real mail, not just a
hand-trimmed clean case.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_pokemoncenter import parse_shipped_lines

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


BODY = (
    "Order Summary |\n"
    "\n"
    "                                  | Pokémon TCG: 30th Celebration Mini Tins (10-Pack) |\n"
    "\n"
    "                                  | SKU #\n"
    "                                      : 10-10465-176\n"
    "                                      Qty\n"
    "                                      : 1 |\n"
    "\n"
    "                            | SKU #\n"
    "                                      : 10-10465-176\n"
    "                                      Qty\n"
    "                                      : 1 | SKU #\n"
    "                                      : 10-10465-176\n"
    "                                      Qty\n"
    "                                      : 1 |\n"
    "\n"
    "                                  |  |\n"
    "\n"
    "                            |  |  |\n"
    "\n"
    "                                  | Pokémon TCG: 30th Celebration Booster Bundle (6 Packs) |\n"
    "\n"
    "                                  | SKU #\n"
    "                                      : 10-10451-115\n"
    "                                      Qty\n"
    "                                      : 3 |\n"
    "\n"
    "                            | SKU #\n"
    "                                      : 10-10451-115\n"
    "                                      Qty\n"
    "                                      : 3 | SKU #\n"
    "                                      : 10-10451-115\n"
    "                                      Qty\n"
    "                                      : 3 |\n"
    "\n"
    "                      | SKU #\n"
    "                                      : 10-10451-115\n"
    "                                      Qty\n"
    "                                      : 3 | SKU #\n"
    "                                      : 10-10451-115\n"
    "                                      Qty\n"
    "                                      : 3 | SKU #\n"
    "                                      : 10-10451-115\n"
    "                                      Qty\n"
    "                                      : 3 |\n"
)

lines = parse_shipped_lines(BODY)

check("exactly 2 lines extracted, not 0 and not the mangled duplicates", len(lines), 2)
if len(lines) == 2:
    check(
        "line 1: Mini Tins, correct SKU and qty",
        (lines[0].raw_product_text, lines[0].external_sku, lines[0].quantity),
        ("Pokémon TCG: 30th Celebration Mini Tins (10-Pack)", "10-10465-176", 1),
    )
    check(
        "line 2: Booster Bundle, correct SKU and qty",
        (lines[1].raw_product_text, lines[1].external_sku, lines[1].quantity),
        ("Pokémon TCG: 30th Celebration Booster Bundle (6 Packs)", "10-10451-115", 3),
    )

# A single-product SHIPPED email in this shape, with no dangling trailer --
# the common case (14 of the 16 real stuck orders were single-line carts).
ONE_LINE_BODY = (
    "Order Summary |\n"
    "\n"
    "                                  | Pokémon TCG: Mega Evolution Booster Box |\n"
    "\n"
    "                                  | SKU #\n"
    "                                      : 10-99999-001\n"
    "                                      Qty\n"
    "                                      : 1 |\n"
)
one = parse_shipped_lines(ONE_LINE_BODY)
check("single-product email: exactly 1 line", len(one), 1)
if one:
    check(
        "single-product email: correct fields",
        (one[0].raw_product_text, one[0].external_sku, one[0].quantity),
        ("Pokémon TCG: Mega Evolution Booster Box", "10-99999-001", 1),
    )

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
