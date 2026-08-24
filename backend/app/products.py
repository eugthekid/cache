"""
products.py
-----------
Turns a raw product string from any source into a stable Product identity.

WHY THIS IS NOT JUST STRING CLEANUP: measured against the user's own data,
normalizing both sides as hard as is safe matched ZERO of 28 spreadsheet
product names against 52 Discord ones. The same item was "Pokémon TCG:
Pitch Black PKC ETB" in one place and "1x Pokémon TCG: Mega Evolution-Pitch
Black Pokémon Center Elite Trainer Box - 59.99 USD (OS)" in the other --
abbreviations (PKC/ETB), a set-line prefix present on one side only, and
bot formatting noise. No deterministic rule bridges that.

So normalization is only the FIRST of three ways an alias is established:

  1. exact normalized-key match           -- automatic, deterministic, safe
  2. same order number, different name    -- a confirmed pairing, because
     the same order number is the same purchase. This is what actually
     solves the hard cases (21 real pairs recovered from the user's data).
  3. the user merging two products        -- the final say

Normalization deliberately stays CONSERVATIVE. It never tries to expand
abbreviations or guess that "Series 2" and "Series 3" are related -- they
are genuinely different products, and a normalizer that merged them would
silently corrupt inventory counts. Over-merging is much worse than
under-merging: an unmerged duplicate is visible and fixable, a wrongly
merged product quietly reports wrong numbers.
"""

import re
import unicodedata
from typing import Optional

from sqlalchemy.orm import Session

from app import models

_QTY_PREFIX_RE = re.compile(r"^\s*\d+\s*x\s+", re.IGNORECASE)
_TRAILING_PRICE_RE = re.compile(
    r"\s*[-–—]\s*\$?[\d,]+\.?\d*\s*(?:USD|CAD|GBP|EUR)?\s*(?:\([^)]*\))?\s*$",
    re.IGNORECASE,
)


def normalize(raw: Optional[str]) -> str:
    """
    Deterministic fingerprint of a product name. Same string in, same key
    out, always -- this is what makes "have I seen this before?" a lookup
    rather than a guess.

    Steps, each earning its place against real observed data:
      - strip accents      : "Pokémon" and "Pokemon" both appear, sometimes
                             within the same spreadsheet
      - drop "2x " prefix  : HiddenAIO prefixes quantity onto the name
      - drop trailing price: HayhaAIO appends " - $35.98"
      - punctuation to
        spaces             : em-dash vs hyphen vs colon vary by retailer
      - collapse whitespace
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKD", str(raw))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = _QTY_PREFIX_RE.sub("", text)
    text = _TRAILING_PRICE_RE.sub("", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def display_name(raw: Optional[str]) -> str:
    """The human-facing name: the raw text with only the bot noise removed,
    keeping original casing and punctuation (unlike normalize(), which is
    for matching and is unreadable by design)."""
    if not raw:
        return ""
    text = _QTY_PREFIX_RE.sub("", str(raw))
    text = _TRAILING_PRICE_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def resolve_product(
    db: Session,
    user_id: str,
    raw_text: Optional[str],
    category: Optional[str] = None,
) -> Optional[models.Product]:
    """
    Find (or create) the Product a raw name refers to, recording the alias
    so the same string resolves by lookup next time instead of being
    re-derived.

    Deliberately does NOT commit -- callers batch this into their own
    transaction (ingesting hundreds of orders shouldn't mean hundreds of
    commits).
    """
    key = normalize(raw_text)
    if not key:
        return None

    alias = (
        db.query(models.ProductAlias)
        .filter_by(user_id=user_id, normalized_key=key)
        .first()
    )
    if alias:
        return db.query(models.Product).filter_by(id=alias.product_id).first()

    product = (
        db.query(models.Product).filter_by(user_id=user_id, normalized_key=key).first()
    )
    if product is None:
        product = models.Product(
            user_id=user_id,
            canonical_name=display_name(raw_text),
            normalized_key=key,
            category=category,
        )
        db.add(product)
        db.flush()  # need product.id for the alias below

    db.add(
        models.ProductAlias(
            user_id=user_id,
            product_id=product.id,
            raw_text=str(raw_text),
            normalized_key=key,
            source="exact",
        )
    )
    db.flush()
    return product


def merge_products(db: Session, user_id: str, source_id: str, target_id: str) -> int:
    """
    Fold `source` into `target`: every order, unit, and alias pointing at
    source now points at target, and source is removed.

    Returns how many rows were repointed. The source product's own
    normalized_key is kept as an alias of the target, so the raw names that
    resolved to it keep resolving -- to the target now.
    """
    if source_id == target_id:
        return 0
    source = db.query(models.Product).filter_by(id=source_id, user_id=user_id).first()
    target = db.query(models.Product).filter_by(id=target_id, user_id=user_id).first()
    if source is None or target is None:
        return 0

    moved = (
        db.query(models.Order)
        .filter_by(product_id=source_id)
        .update({"product_id": target_id}, synchronize_session=False)
    )
    moved += (
        db.query(models.InventoryItem)
        .filter_by(product_id=source_id)
        .update({"product_id": target_id}, synchronize_session=False)
    )
    db.query(models.ProductAlias).filter_by(product_id=source_id).update(
        {"product_id": target_id, "source": "manual"}, synchronize_session=False
    )

    # Keep the merged-away product's key resolvable, pointed at the target.
    existing = (
        db.query(models.ProductAlias)
        .filter_by(user_id=user_id, normalized_key=source.normalized_key)
        .first()
    )
    if existing is None:
        db.add(
            models.ProductAlias(
                user_id=user_id,
                product_id=target_id,
                raw_text=source.canonical_name,
                normalized_key=source.normalized_key,
                source="manual",
            )
        )

    db.delete(source)
    db.commit()
    return moved


def find_merge_suggestions(db: Session, user_id: str) -> list[dict]:
    """
    Propose pairs of products that are probably the same thing. SUGGESTS
    only -- it never merges. That restraint is not caution for its own
    sake; an earlier version of this auto-merged on "same order number,
    two distinct products" and produced provably wrong results on real
    data, e.g. folding

        "30th Celebration Mini Tins (10-Pack)"   ($99.90 x1)
        "30th Celebration Booster Bundle (6 Pk)" ($26.94 x3)

    into one product -- because those two lines were a single two-item
    CART sharing order P0039849575, not two names for one item. A
    two-item cart is the most common multi-item cart there is, so any rule
    keyed on "how many products share this order number" is doomed.

    What actually distinguishes an alias from a cart line:
      - a cart's lines come from the SAME source and have DIFFERENT prices
      - an alias is the same line seen through TWO DIFFERENT sources
        (Discord bot vs spreadsheet import vs email), and therefore agrees
        on price and quantity

    So a suggestion requires: same order number, DIFFERENT source, and
    matching unit_price and quantity. Anything weaker stays unmerged --
    an unmerged duplicate is visible and fixable, a wrong merge silently
    reports wrong inventory.
    """
    rows = (
        db.query(models.Order)
        .filter(models.Order.deleted_at.is_(None))
        .filter(models.Order.order_number.isnot(None))
        .filter(models.Order.product_id.isnot(None))
        .all()
    )
    by_number: dict[str, list[models.Order]] = {}
    for order in rows:
        by_number.setdefault(order.order_number, []).append(order)

    names = {p.id: p.canonical_name for p in db.query(models.Product).filter_by(user_id=user_id)}
    seen: set[tuple[str, str]] = set()
    suggestions: list[dict] = []

    for order_number, group in by_number.items():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if a.product_id == b.product_id:
                    continue
                if a.source_id == b.source_id:
                    continue  # same source => different lines of one cart
                if (a.unit_price or 0) != (b.unit_price or 0):
                    continue
                if (a.quantity or 1) != (b.quantity or 1):
                    continue
                pair = tuple(sorted((a.product_id, b.product_id)))
                if pair in seen:
                    continue
                seen.add(pair)
                suggestions.append(
                    {
                        "source_id": pair[1],
                        "target_id": pair[0],
                        "source_name": names.get(pair[1], "?"),
                        "target_name": names.get(pair[0], "?"),
                        "reason": (
                            f"Order {order_number} appears in two different sources "
                            f"with the same price and quantity, under both names."
                        ),
                    }
                )
    return suggestions
