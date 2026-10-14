"""The Pokémon naming convention: "Pokémon TCG: <Set> <Product>"."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.catalog import standard_pokemon_name as std

passed = failed = 0


def check(label, got, want):
    global passed, failed
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        expected: {want!r}\n        got:      {got!r}")
    passed, failed = passed + ok, failed + (not ok)


check("set is added in front of the product", std("Premium Poster Collection: Mega Gardevoir", "ME: Ascended Heroes"),
      "Pokémon TCG: Ascended Heroes Premium Poster Collection: Mega Gardevoir")
check("a set already in the name isn't repeated", std("30th Celebration Sylveon ex Box", "ME: 30th Celebration"),
      "Pokémon TCG: 30th Celebration Sylveon ex Box")
check("the series is dropped, the set kept", std("Mega Evolution: Ascended Heroes Tech Sticker Collection - Gastly", "ME: Ascended Heroes"),
      "Pokémon TCG: Ascended Heroes Tech Sticker Collection - Gastly")
check("a set that only repeats the name's first words is not added", std("First Partner Illustration Collection (Series 2)", "First Partner Collection 2026"),
      "Pokémon TCG: First Partner Illustration Collection (Series 2)")
check("a different set name is added", std("Unova Heavy Hitters Premium Collection", "SV: Black Bolt"),
      "Pokémon TCG: Black Bolt Unova Heavy Hitters Premium Collection")
check("miscellaneous is not a set", std("Stacking Tin", "Miscellaneous Cards & Products"), "Pokémon TCG: Stacking Tin")
check("no set at all", std("Poke Ball Tin", None), "Pokémon TCG: Poke Ball Tin")
check("an existing site prefix is replaced, not doubled", std("Pokémon Trading Card Game: 30th Celebration Tin", "ME: 30th Celebration"),
      "Pokémon TCG: 30th Celebration Tin")
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
