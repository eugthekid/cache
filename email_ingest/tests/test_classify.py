"""
Every subject string below is copied VERBATIM from a real email pulled
from the connected inbox during the 2026-09-16 reconnaissance -- none are
invented. Thread/order IDs are noted so a claim here can be re-verified
against the source mail if the templates ever drift.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from classify import Retailer, EmailKind, classify

passed = failed = 0


def check(label, subject, want_retailer, want_kind, want_number):
    global passed, failed
    got = classify(subject)
    ok = (got.retailer, got.kind, got.order_number) == (want_retailer, want_kind, want_number)
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        subject:  {subject!r}")
        print(f"        expected: {(want_retailer, want_kind, want_number)}")
        print(f"        got:      {(got.retailer, got.kind, got.order_number)}")
    if ok:
        passed += 1
    else:
        failed += 1


print("=== Pokémon Center ===")
check(
    "confirmation (thread 19f675e3a4060d74)",
    "Thank you for shopping at PokemonCenter.com!",
    Retailer.POKEMON_CENTER, EmailKind.CONFIRMATION, None,
)
check(
    "shipped (thread 19f6bbe0ad6c1533)",
    "Your Pokémon Center order is on its way!",
    Retailer.POKEMON_CENTER, EmailKind.SHIPPED, None,
)
check(
    "cancelled, no number in subject (thread 1a07c77cd70be10f, order P0038875758)",
    "Your order has been canceled",
    Retailer.POKEMON_CENTER, EmailKind.CANCELLED_FULL, None,
)

print("\n=== Target ===")
check(
    "confirmation (thread 19e4e800e1e6f6c5)",
    "Thanks for shopping with us! Here's your order #:912003448396552.",
    Retailer.TARGET, EmailKind.CONFIRMATION, "912003448396552",
)
check(
    "shipped (thread 19e6b86e1e42efbb)",
    "Get ready for something special! Items from order #912003448396552 are about to ship.",
    Retailer.TARGET, EmailKind.SHIPPED, "912003448396552",
)
check(
    "arrives tomorrow (thread 19e794ea3bfcb8c2)",
    "Your order arrives tomorrow! Order #912003448396552",
    Retailer.TARGET, EmailKind.SHIPPED, "912003448396552",
)
check(
    "arrived (thread 19e84e985626f848)",
    "Items have arrived from order #912003448396552!",
    Retailer.TARGET, EmailKind.ARRIVED, "912003448396552",
)
check(
    "full cancel, retailer-initiated (thread 19c9e2402218b025, order 102003302959415)",
    "Sorry, we had to cancel order #102003302959415.",
    Retailer.TARGET, EmailKind.CANCELLED_FULL, "102003302959415",
)
check(
    "partial cancel, user-initiated (thread 19916e47671de66e, order 102002382211975)",
    "You've successfully canceled items from your order ending in 1975.",
    Retailer.TARGET, EmailKind.CANCELLED_PARTIAL, None,
)
check(
    "preorder payment reminder (thread 1a07a3e1153f0228, order 902003604924735)",
    "Release day is getting closer! We’ll process your preorder payment soon #902003604924735",
    Retailer.TARGET, EmailKind.PAYMENT_PENDING, "902003604924735",
)

print("\n=== Walmart ===")
check(
    "confirmation (thread 19fb16c3b8b9a43d, order 2000149-57672472)",
    "Thanks for your delivery order, Eugene",
    Retailer.WALMART, EmailKind.CONFIRMATION, None,
)
check(
    "preorder confirmation (thread 199c947738cf5445)",
    "Eugene, thanks for your preorder",
    Retailer.WALMART, EmailKind.CONFIRMATION, None,
)
check(
    "shipped (thread 19fcdf028a3903d7)",
    "Shipped: Pokemon Trading Card G...",
    Retailer.WALMART, EmailKind.SHIPPED, None,
)
check(
    "arrived (thread 19fd30f3416361d0)",
    "Arrived: Your Pokemon Trading Card G...",
    Retailer.WALMART, EmailKind.ARRIVED, None,
)
check(
    "cancelled, order number in subject (thread 199c94785f7cf1c3)",
    "Canceled: delivery from order #200013725750475",
    Retailer.WALMART, EmailKind.CANCELLED_FULL, "200013725750475",
)

print("\n=== Not a checkout email at all ===")
check(
    "marketing, must not misclassify",
    "Our biggest Black Friday Deals start now \U0001f6a8",
    None, EmailKind.UNRECOGNIZED, None,
)
check(
    "Target Circle welcome, must not misclassify",
    "Thank you for joining Target Circle™",
    None, EmailKind.UNRECOGNIZED, None,
)
check(
    "Walmart+ membership, must not misclassify",
    "Eugene, your Walmart+ benefits expire tomorrow!",
    None, EmailKind.UNRECOGNIZED, None,
)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
