"""
catalog.py
----------
Syncs an external product catalog and matches your own products against
it, to fill in a clean name and an image without hand-typing either.

WHY tcgtracking.com: verified against real orders before building this --
pokemontcg.io only indexes individual cards (zero hits for "Elite Trainer
Box"), TCGPlayer's public API has been closed to new developers since
late 2024, and PriceCharting's sealed-product coverage has real gaps (no
"30th Celebration", no "Pitch Black" -- exactly the sets bought at
release before a resale market exists for them). tcgtracking has a
dedicated /sealed endpoint, product images, no API key, and covers both
Pokemon and One Piece.

MATCHING DISCIPLINE, same as products.py's alias learning: an EXACT
normalized match auto-applies, because it's deterministic. Anything less
becomes a SUGGESTION for a human to confirm, never an automatic guess --
products.py already burned us once on over-eager auto-matching (folding
two lines of one cart into one product because they shared an order
number), so a wrong catalog match carrying a wrong image is exactly the
kind of confidently-incorrect result that discipline exists to prevent.
"""

import re
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, products

BASE_URL = "https://openapi.tcgtracking.com/tcgapi/v1"
# The API 403s Python's default urllib user-agent but accepts a normal
# browser one -- undocumented, found by testing, not a documented
# requirement, so it may need revisiting if it changes.
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Cache/0.4"}

CATEGORY_IDS = {
    "pokemon": 3,
    "onepiece": None,  # resolved from /categories at sync time; ids can change
}

# Display label for Product.category, keyed by CatalogProduct.category.
CATEGORY_LABELS = {"pokemon": "Pokemon", "onepiece": "One Piece"}


def catalog_display_name(catalog_product: "models.CatalogProduct") -> str:
    """
    The name a Product takes on when it's matched to this catalog entry.
    Prefixed by game/franchise so it reads consistently in a product list
    once non-TCG categories (sneakers, apparel) sit alongside it --
    without it, a booster box and a pair of sneakers look like the same
    kind of thing at a glance. Colon, not a dash, for every game -- "X: "
    is the one shared convention across all of them.
    """
    if catalog_product.category == "pokemon":
        return f"Pokémon TCG: {catalog_product.name}"
    if catalog_product.category == "onepiece":
        return f"One Piece: {catalog_product.name}"
    return catalog_product.name


def _get_json(url: str, retries: int = 3) -> dict:
    """GETs with retries and backoff -- pulling all sets in one sync hits
    this API hundreds of times in a row, and it rate-limited a chunk of
    those calls when tested at full speed with no delay at all."""
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                import json

                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"tcgtracking request failed after {retries} tries: {last_error}")


def _resolve_category_id(category: str) -> int:
    if CATEGORY_IDS.get(category):
        return CATEGORY_IDS[category]
    data = _get_json(f"{BASE_URL.replace('/tcgapi','')}/categories")
    for c in data.get("categories", []):
        name = c.get("name", "").lower()
        if category == "onepiece" and "one piece" in name:
            return c["id"]
        if category == "pokemon" and name == "pokemon":
            return c["id"]
    raise ValueError(f"Unknown category: {category}")


def sync_catalog(db: Session, category: str) -> dict:
    """
    Pulls every sealed product across every set for one category and
    upserts it into catalog_products. Slow (one request per set, ~285 for
    Pokemon) and meant to be run explicitly and occasionally, not on every
    page load -- callers should treat this as a background/manual action.
    """
    cat_id = _resolve_category_id(category)
    sets_data = _get_json(f"{BASE_URL}/{cat_id}/sets")
    sets = sets_data.get("sets", [])

    upserted, failed = 0, 0
    for s in sets:
        try:
            sealed = _get_json(f"{BASE_URL}/{cat_id}/sets/{s['id']}/sealed")
        except RuntimeError:
            failed += 1
            continue
        for p in sealed.get("products") or sealed.get("sealed") or []:
            external_id = str(p.get("id") or f"{s['id']}:{p.get('name')}")
            existing = (
                db.query(models.CatalogProduct)
                .filter_by(source="tcgtracking", external_id=external_id)
                .first()
            )
            key = normalize_catalog_name(p.get("name", ""))
            if existing:
                existing.name = p.get("name", existing.name)
                existing.normalized_key = key
                existing.image_url = p.get("image_url") or existing.image_url
                existing.set_name = s.get("name")
            else:
                db.add(
                    models.CatalogProduct(
                        source="tcgtracking",
                        external_id=external_id,
                        category=category,
                        set_name=s.get("name"),
                        name=p.get("name", ""),
                        normalized_key=key,
                        image_url=p.get("image_url"),
                    )
                )
            upserted += 1
        time.sleep(0.2)  # observed 403s/timeouts pulling all sets back-to-back with no delay
    db.commit()
    return {"sets": len(sets), "sets_failed": failed, "products_upserted": upserted}


# Rules specific to bridging RETAILER vocabulary to CATALOG vocabulary --
# distinct from products.py's normalize(), which only strips bot-added
# noise (quantity prefixes, trailing prices) and never rewrites words.
# Order matters: e.g. "PKC" must expand to "pokemon center" BEFORE the
# generic stray-"pokemon" strip runs, or the expansion is immediately
# undone. Verified against 32 real product names (37% -> 75% exact match)
# and the real tcgtracking catalog, not assumed.
_VOCAB_RULES = [
    (r"\btrading card game\b", ""),
    (r"\bpokemon tcg\b", ""),
    (r"\bscarlet\s*&?\s*violet\b", ""),
    (r"\bmega evolution\b", ""),
    (r"\bme\d*\s*:", ""),
    (r"\bsv\d*\s*:", ""),
    (r"\banniversary\b", "celebration"),
    (r"\bpkc\b", "pokemon center"),
    (r"\betb\b", "elite trainer box"),
    (r"\bupc\b", "ultra premium collection"),
    (r"booster display box\s*\(?36\s*packs?\)?", "booster box"),
    (r"\(\d+\s*packs?\)", ""),
    (r"\(\d+\s*cards?\)", ""),
    (r"\((n/?a|exclusive)\)", ""),
    (r"3 booster packs? & (\w+) promo card", r"3 pack blister \1"),
    (r"[^a-z0-9]+", " "),
    (r"(?<!center )\bpokemon\b(?!\s*center)", ""),
]


def normalize_catalog_name(raw: Optional[str]) -> str:
    if not raw:
        return ""
    text = unicodedata.normalize("NFKD", str(raw))
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Split a lower->upper boundary BEFORE lowercasing (needs the case info
    # to find it) -- catches real retailer typos like "CollectionSeries 2"
    # (missing the space Target should have typed), which otherwise stays
    # one token and silently misses a catalog match by a hair: verified,
    # "collectionseries" vs "collection series" scored 0.571 against a
    # 0.6 threshold for the exact real product this happened on. Safe
    # because a genuine single word is never itself internally cased like
    # this in these product names -- splitting only ever un-mashes two
    # words that should have had a space, it can't wrongly split a real one.
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text).lower()
    for pattern, repl in _VOCAB_RULES:
        text = re.sub(pattern, repl, text)
    return re.sub(r"\s+", " ", text).strip()


def _token_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity over token sets. Every call site already has
    tokenized sets in hand (from splitting a normalized_key once), so this
    takes sets directly rather than re-splitting strings on every call."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _merge_shared_catalog_matches(db: Session, user_id: str) -> int:
    """
    Folds together any products that both ended up CONFIRMED against the
    same catalog item.

    Found live in real data: two Products with different normalized_key
    (one carrying a "Mega Evolution" prefix the other lacked) each matched
    the same catalog product independently, both got renamed to the
    identical display name, and sat as two separate rows in the grouped
    Inventory view -- reading as a plain duplicate even though nothing
    about the matching logic was wrong, it just never occurred to either
    match that the OTHER product existed.

    Merging on a SHARED CONFIRMED CATALOG MATCH is safe in the way the
    order-number merge in products.py had to be guarded against being --
    two products matching the exact same external catalog entry is
    strictly stronger evidence than a coincidence could produce.
    """
    confirmed = (
        db.query(models.Product)
        .filter_by(user_id=user_id, catalog_match_status="confirmed")
        .filter(models.Product.catalog_product_id.isnot(None))
        .all()
    )
    by_catalog_id: dict[str, list[models.Product]] = {}
    for p in confirmed:
        by_catalog_id.setdefault(p.catalog_product_id, []).append(p)

    order_counts = dict(
        db.query(models.Order.product_id, func.count(models.Order.id))
        .group_by(models.Order.product_id)
        .all()
    )

    merged = 0
    for group in by_catalog_id.values():
        if len(group) < 2:
            continue
        # Keep whichever already has the most orders attached, so the
        # surviving row is the one the user is more likely to already
        # recognize -- id as a tiebreaker only for determinism.
        group.sort(key=lambda p: (-order_counts.get(p.id, 0), p.id))
        target = group[0]
        for extra in group[1:]:
            if products.merge_products(db, user_id, source_id=extra.id, target_id=target.id):
                merged += 1
    return merged


def find_catalog_matches(db: Session, user_id: str) -> dict:
    """
    Matches every unresolved Product against the local catalog cache.
    EXACT normalized matches auto-confirm; anything else scoring >= 0.6
    becomes a suggestion; below that, or with no candidate at all, is left
    alone rather than guessed at.

    Skips products already 'confirmed' (no rework) and candidates already
    'rejected' for a given product (so declining a suggestion sticks).
    """
    catalog = db.query(models.CatalogProduct).all()
    by_key: dict[str, models.CatalogProduct] = {}
    for c in catalog:
        by_key.setdefault(c.normalized_key, c)
    tokenized = [(set(c.normalized_key.split()), c) for c in catalog]

    products = (
        db.query(models.Product)
        .filter(models.Product.user_id == user_id)
        .filter(models.Product.catalog_match_status != "confirmed")
        .all()
    )

    auto_confirmed = suggested = unmatched = 0
    for product in products:
        key = normalize_catalog_name(product.canonical_name)
        if not key:
            unmatched += 1
            continue

        exact = by_key.get(key)
        if exact and exact.id != product.catalog_rejected_id:
            product.catalog_product_id = exact.id
            product.catalog_match_status = "confirmed"
            # This IS the standardization the user asked for -- matching
            # without renaming would only ever add a picture, never fix
            # "CollectionSeries 2" or the missing-space/price-in-title
            # cases. Safe here specifically because it's an EXACT
            # normalized match, not a guess.
            product.canonical_name = catalog_display_name(exact)
            product.category = CATEGORY_LABELS.get(exact.category, exact.category)
            auto_confirmed += 1
            continue

        my_tokens = set(key.split())
        best: Optional[tuple[float, models.CatalogProduct]] = None
        for tokens, candidate in tokenized:
            if candidate.id == product.catalog_rejected_id:
                continue
            score = _token_similarity(my_tokens, tokens)
            if score >= 0.6 and (not best or score > best[0]):
                best = (score, candidate)

        if best:
            product.catalog_product_id = best[1].id
            product.catalog_match_status = "suggested"
            suggested += 1
        else:
            unmatched += 1

    db.commit()
    merged = _merge_shared_catalog_matches(db, user_id)

    return {
        "duplicates_merged": merged,
        "auto_confirmed": auto_confirmed,
        "suggested": suggested,
        "unmatched": unmatched,
    }
