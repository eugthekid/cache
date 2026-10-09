"""
Fixture trimmed from a REAL Pokemon Center confirmation email (order
P0038927021, Gmail uid captured 2026-10-08).

ROOT CAUSE this pins: the template renders each line item as "SKU #: ...",
"Qty: N", a blank row, then "Price: $X |" on SEPARATE lines -- not the
one-line row parse_confirmation originally expected -- so it returned []
for every real confirmation. No Pokemon Center order ever got an email
price, and each kept the Discord bot's pre-tax cart price: an Elite Trainer
Box sat at $59.99 when it really cost about $65.31 after tax.

Also pins the shipping rule (user, 2026-10-08): shipping is a flat
per-order charge, split EQUALLY across the order's lines, while tax stays
proportional to each line's price.

The repeat renderings PC adds at shallower nesting (including the mangled
ones, e.g. "Price: $14.99 | SKU #: 10-10449-122") are kept as received:
they must never produce extra or doubled lines.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.email_ingest.parse_pokemoncenter import parse_confirmation

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


def row(sku, qty, price):
    return (
        f"                        | SKU #: {sku}\n"
        f"                                    Qty: {qty}\n"
        "\n"
        f"         Price: ${price} |\n"
        "\n"
        f"                        | SKU #: {sku}\n"
        f"                                    Qty: {qty}\n"
        "\n"
        f"         Price: ${price} | SKU #: {sku}\n"
        f"                                    Qty: {qty}\n"
        "\n"
        f"         Price: ${price} |\n"
        "\n"
    )


def body(shipping="0.00", subtotal="149.96", tax="13.31"):
    return (
        "Order Number: P0038927021 Date Ordered: July 15, 2026\n"
        "Order Summary |\n\n"
        "                              | Pokémon TCG: 30th Celebration Tech Sticker Collection (Lucario) |\n\n"
        + row("10-10449-122", 1, "14.99")
        + "               |  |\n\n            |  |  |\n\n"
        "                              | Pokémon TCG: 30th Celebration Tech Sticker Collection (Alolan Exeggutor) |\n\n"
        + row("10-10449-121", 1, "14.99")
        + "               |  |\n\n            |  |  |\n\n"
        "                              | Pokémon TCG: 30th Celebration Pokémon Center Elite Trainer Box |\n\n"
        + row("10-10447-111", 2, "59.99")
        + f"                                    | Order Subtotal | ${subtotal} |\n\n"
        f"                                    | Sales Tax | ${tax} |\n\n"
        f"                                    | Shipping | ${shipping} |\n\n"
    )


# --- the real email: no shipping --------------------------------------------
lines = parse_confirmation(body())
check("all 3 lines parsed (was 0), none doubled by the repeat renderings", len(lines), 3)
if len(lines) == 3:
    check(
        "names, SKUs and quantities",
        [(l.raw_product_text.split(": ", 1)[1], l.external_sku, l.quantity) for l in lines],
        [
            ("30th Celebration Tech Sticker Collection (Lucario)", "10-10449-122", 1),
            ("30th Celebration Tech Sticker Collection (Alolan Exeggutor)", "10-10449-121", 1),
            ("30th Celebration Pokémon Center Elite Trainer Box", "10-10447-111", 2),
        ],
    )
    etb = lines[2]
    check("Elite Trainer Box: $59.99 + its share of tax = ~$65.31 per unit", round(etb.unit_price, 2), 65.31)
    check("the lines add up to the order total, $163.27", round(sum(l.unit_price * l.quantity for l in lines), 2), 163.27)

# --- shipping is split equally across lines, tax stays proportional ----------
lines = parse_confirmation(body(shipping="9.00"))
check("with $9.00 shipping, still 3 lines", len(lines), 3)
if len(lines) == 3:
    pretax = 14.99 + 14.99 + 2 * 59.99
    for l, ext in zip(lines, (14.99, 14.99, 2 * 59.99)):
        expected = (ext + ext / pretax * 13.31 + 9.00 / 3) / l.quantity
        check(f"{l.external_sku}: tax by price, shipping a flat third", round(l.unit_price, 4), round(expected, 4))
    check("the lines add up to subtotal + tax + shipping, $172.27", round(sum(l.unit_price * l.quantity for l in lines), 2), 172.27)

# --- a mismatch with the stated subtotal still refuses to guess --------------
check("subtotal that doesn't match the parsed lines -> []", parse_confirmation(body(subtotal="140.00")), [])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
