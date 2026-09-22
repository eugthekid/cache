"""
Exercises products.py's normalize() directly -- pure function, no DB.

Guards the TCG-expansion fix (2026-09-18): found live, "Pokémon TCG:
Greninja ex Box" (Discord) and "Pokémon Trading Card Game: Greninja ex
Box" (email confirmation) were two separate Product rows because
normalize() treated "TCG" and "Trading Card Game" as different tokens.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.products import normalize

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
    "TCG and Trading Card Game normalize to the same key",
    normalize("Pokémon TCG: 30th Celebration Greninja ex Box"),
    normalize("Pokémon Trading Card Game: 30th Celebration Greninja ex Box"),
)
check(
    "TCG expands to the full phrase",
    normalize("Pokémon TCG: Test Box"),
    "pokemon trading card game test box",
)
check(
    "a word merely containing 'tcg' is untouched (whole-word match only)",
    normalize("Wintcgarden Box"),
    "wintcgarden box",
)
check(
    "accent stripping still works alongside the TCG expansion",
    normalize("Pokemon TCG: Test Box"),
    normalize("Pokémon Trading Card Game: Test Box"),
)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
