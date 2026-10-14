"""The Pokémon naming convention: "Pokémon TCG: <Set> <Product> - <Variant>"."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.catalog import catalog_display_name, colon_variant, standard_pokemon_name as std
from app.database import Base

passed = failed = 0


def check(label, got, want):
    global passed, failed
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        print(f"        expected: {want!r}\n        got:      {got!r}")
    passed, failed = passed + ok, failed + (not ok)


# --- the set -----------------------------------------------------------------
check("a generic type gets its set", std("Elite Trainer Box", "SV: Prismatic Evolutions"), "Pokémon TCG: Prismatic Evolutions Elite Trainer Box")
check("a set already in the name isn't repeated", std("30th Celebration Sylveon ex Box", "ME: 30th Celebration"), "Pokémon TCG: 30th Celebration Sylveon ex Box")
check("the series is dropped, the set kept", std("Mega Evolution: Ascended Heroes Tech Sticker Collection - Gastly", "ME: Ascended Heroes"),
      "Pokémon TCG: Ascended Heroes Tech Sticker Collection - Gastly")
check("a named product stands on its own", std("Unova Heavy Hitters Premium Collection", "SV: Black Bolt"), "Pokémon TCG: Unova Heavy Hitters Premium Collection")
check("a set that only repeats the name's first words is not added", std("First Partner Illustration Collection (Series 2)", "First Partner Collection 2026"),
      "Pokémon TCG: First Partner Illustration Collection (Series 2)")
check("miscellaneous is not a set", std("Stacking Tin", "Miscellaneous Cards & Products"), "Pokémon TCG: Stacking Tin")
check("no set at all", std("Poke Ball Tin", None), "Pokémon TCG: Poke Ball Tin")
check("an existing site prefix is replaced, not doubled", std("Pokémon Trading Card Game: 30th Celebration Tin", "ME: 30th Celebration"), "Pokémon TCG: 30th Celebration Tin")

# --- variants always after a dash ------------------------------------------------
check("brackets become a dash", std("Ascended Heroes Tin [Mega Emboar ex]", "ME: Ascended Heroes"), "Pokémon TCG: Ascended Heroes Tin - Mega Emboar ex")
check("a generic type with a bracket variant gets the set too", std("Tin [Mega Emboar ex]", "ME: Ascended Heroes"), "Pokémon TCG: Ascended Heroes Tin - Mega Emboar ex")
check("parentheses become a dash", std("Figure Collection (Mew)", "ME: 30th Celebration"), "Pokémon TCG: 30th Celebration Figure Collection - Mew")
check("a dash stays a dash", std("30th Celebration Tech Sticker Collection - Lucario", "ME: 30th Celebration"), "Pokémon TCG: 30th Celebration Tech Sticker Collection - Lucario")
check("a catalog-proven colon variant becomes a dash", std("Premium Poster Collection: Mega Gardevoir", "ME: Ascended Heroes", ("Premium Poster Collection", "Mega Gardevoir")),
      "Pokémon TCG: Ascended Heroes Premium Poster Collection - Mega Gardevoir")
check("random: 'or' variant, 'Styles May Vary' dropped", std("Pokémon TCG: 30th Celebration Tin (Sylveon or Greninja)- Styles May Vary", None),
      "Pokémon TCG: 30th Celebration Tin - Sylveon or Greninja")
check("random with no options keeps the words", std("Surprise Tin - Styles May Vary", None), "Pokémon TCG: Surprise Tin - Styles May Vary")
check("(Series 2) and (Exclusive) are not variants", std("Pokemon Center Elite Trainer Box (Exclusive)", "SV: Pitch Black"),
      "Pokémon TCG: Pitch Black Pokemon Center Elite Trainer Box (Exclusive)")

# --- a colon is a variant only when the catalog shows siblings --------------------
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()


def cp(name, set_name="ME: Ascended Heroes"):
    c = models.CatalogProduct(external_id=name, category="pokemon", set_name=set_name, name=name, normalized_key=name.lower())
    db.add(c)
    db.commit()
    return c


gard = cp("Premium Poster Collection: Mega Gardevoir")
cp("Premium Poster Collection: Mega Lucario")
cp("Premium Poster Collection Case")
lone = cp("Booster Pack: Mega Zygarde")
ser = cp("Mega Evolution: Ascended Heroes Tech Sticker Collection - Gastly")
cp("Mega Evolution: Ascended Heroes Tech Sticker Collection - Charmander")
misc = cp("Stacking Tin: Dragon", "Miscellaneous Cards & Products")
cp("Stacking Tin: Water", "Miscellaneous Cards & Products")
check("two siblings in the set prove a colon variant", colon_variant(db, gard), ("Premium Poster Collection", "Mega Gardevoir"))
check("a lone colon is just part of the name", colon_variant(db, lone), None)
check("a series prefix is not a product line", colon_variant(db, ser), None)
check("the miscellaneous bucket isn't a set", colon_variant(db, misc), None)
check("display name uses the proof", catalog_display_name(gard, db), "Pokémon TCG: Ascended Heroes Premium Poster Collection - Mega Gardevoir")
check("without the db there's no proof, the colon stays", catalog_display_name(gard), "Pokémon TCG: Premium Poster Collection: Mega Gardevoir")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
