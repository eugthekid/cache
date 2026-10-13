"""
families.py
-----------
Products that are versions of one item -- the 30th Celebration tech stickers
that come as Lucario, Alolan Exeggutor, or a random pick of either -- grouped
so the inventory list shows ONE row for the item and clicking in shows each
version with its own counts, cost and profit.

WHY A GROUP ON TOP OF PRODUCTS rather than a new variants table: each version
already IS a Product, and everything that matters is already keyed on it --
order text resolving to it (aliases, catalog matches), retailers, sales, and
average cost. So "sell a Lucario at the Lucario average" needs no new code,
and a random-variant product is just another product that happens to be a
blind pick. The family only adds the grouping and a label for each version.

VARIANT KINDS: 'specific' (you chose the version), 'random' (blind -- "Styles
May Vary", the version unknown until it's opened), or None (a plain product
that isn't part of a family).
"""

import re
import unicodedata
from collections import Counter, defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from app import models
from app.product_dashboard import (
    COUNTED_STATUSES,
    average_cost,
    original_cost,
    retailer_breakdown,
    units_for_products,
)

VARIANT_KINDS = ("specific", "random")
_STAGE_ORDER = {"in_hand": 0, "in_transit": 1, "not_shipped": 2}

_MAY_VARY = re.compile(r"\s*[-–]\s*Styles May Vary", re.I)
_SITE_PREFIX = re.compile(r"^Pok[eé]mon (?:TCG|Trading Card Game):\s*", re.I)
_SERIES_PREFIX = re.compile(
    r"^(?:Mega Evolution|Scarlet\s*&\s*Violet|Sword\s*&\s*Shield|Sun\s*&\s*Moon|Black\s*&\s*White|XY)\s*[:\-–—]\s*", re.I
)
_BRACKET = re.compile(r"\s*\[([^\]]+)\]\s*")
_PAREN = re.compile(r"\s*\(([^()]+)\)\s*")
# "... Tech Sticker Collection - Gastly": the variant after a trailing hyphen.
_HYPHEN = re.compile(r"\s[-–]\s([A-Z][\w&'. ]{1,28})$")
# Marks that look like a variant but are a different release or SKU, not a
# version of one item: "(Series 2)", "(3 Pack)", "- Pokémon Center Exclusive".
_NOT_A_VARIANT = re.compile(r"^(series \d+|\d+[- ]?packs?|set of \d+|case|display|bundle)$|exclusive", re.I)

# The code the catalog puts in front of a set's name ("ME: Ascended Heroes").
SERIES_NAMES = {
    "ME": "Mega Evolution",
    "SV": "Scarlet & Violet",
    "SWSH": "Sword & Shield",
    "SM": "Sun & Moon",
    "XY": "XY",
    "BW": "Black & White",
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9& ]+", " ", text)).strip()


def _is_variant(token: str) -> bool:
    token = token.strip()
    return bool(token) and len(token) <= 40 and not _NOT_A_VARIANT.search(token)


def split_set(set_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """("ME: Ascended Heroes") -> ("Mega Evolution", "Ascended Heroes")."""
    if not set_name:
        return None, None
    m = re.match(r"^([A-Z]{2,4})\d{0,2}\s*[:\-]\s*(.+)$", set_name.strip())
    if not m:
        return None, set_name.strip()
    return SERIES_NAMES.get(m.group(1)), m.group(2).strip()


def parse_product(name: str, set_name: Optional[str] = None) -> dict:
    """
    Take a product name apart into where it sits and which version it is:

      series   Mega Evolution          (optional; from the catalog's set code)
      set      Ascended Heroes         (from the catalog when matched)
      line     Tech Sticker Collection (what kind of product, within the set)
      variant  Gastly                  (None when it has no version)
      kind     'specific' | 'random' | None
      base     the name with the version taken off

    Versions are written four ways -- "[Lucario]", "(Lucario)", a trailing
    "- Gastly", and "Styles May Vary" / "(A or B)" for blind picks -- and the
    catalog mixes them. Two products belong together when they share set and
    line and differ only in the version.
    """
    series, set_ = split_set(set_name)
    text = _MAY_VARY.sub("", name)
    random = text != name
    variant: Optional[str] = None

    for pattern in (_BRACKET, _PAREN):
        found = [m for m in pattern.finditer(text) if _is_variant(m.group(1))]
        if found:
            m = found[-1]
            variant = m.group(1).strip()
            text = (text[: m.start()] + " " + text[m.end() :]).strip()
            break
    else:
        m = _HYPHEN.search(text)
        if m and _is_variant(m.group(1)):
            variant = m.group(1).strip()
            text = text[: m.start()].strip()

    base = re.sub(r"\s+", " ", _SITE_PREFIX.sub("Pokémon TCG: ", text)).strip()
    line = _SERIES_PREFIX.sub("", _SITE_PREFIX.sub("", text)).strip()
    if set_ and _norm(line).startswith(_norm(set_)):
        line = line[len(set_) :].strip(" :-–—")
    kind = None
    if variant or random:
        kind = "random" if random or (variant and re.search(r"\bor\b", variant, re.I)) else "specific"
    return {"series": series, "set": set_, "line": re.sub(r"\s+", " ", line), "variant": variant, "kind": kind, "base": base}


def family_base(name: str) -> str:
    return parse_product(name)["base"]


def guess_kind(name: str) -> str:
    return parse_product(name)["kind"] or "specific"


def variant_label(name: str, kind: Optional[str]) -> str:
    """What to call one version inside its family: "Lucario", or
    "Random · Lucario or Alolan Exeggutor"."""
    label = parse_product(name)["variant"] or name
    return f"Random · {label}" if kind == "random" else label


def random_options(label: str) -> list[str]:
    """"Random · Lucario or Alolan Exeggutor" -> ["Lucario", "Alolan Exeggutor"]."""
    text = label.removeprefix("Random · ")
    return [part.strip() for part in re.split(r"\s+or\s+|,\s*", text) if part.strip()]


def _unit_counts(db: Session, user_id: str) -> dict[str, int]:
    counts: Counter = Counter()
    rows = (
        db.query(models.InventoryItem, models.Order)
        .outerjoin(models.Order, models.InventoryItem.order_id == models.Order.id)
        .filter(models.InventoryItem.user_id == user_id)
        .filter(models.InventoryItem.deleted_at.is_(None))
        .filter(models.InventoryItem.status.in_(COUNTED_STATUSES))
    )
    for item, order in rows:
        pid = item.product_id or (order.product_id if order else None)
        if pid:
            counts[pid] += 1
    return counts


def auto_group(db: Session, user_id: str) -> int:
    """
    Group products that are versions of one item, with no one asking. Runs
    whenever the product list is read, so a new version that shows up later
    joins its family on its own. Returns how many products were newly grouped.

    Deliberately cautious -- a wrong grouping hides real numbers:
      * Needs the same set AND the same product line (a catalog-matched
        product's set comes from the catalog; unmatched ones group only with
        other unmatched ones of the identical name).
      * Needs at least two products that each carry a version.
      * Two products with the SAME version are left alone: that's a duplicate
        for merging, not two versions.
      * "(Series 2)" / "(3 Pack)" / "Exclusive" are not versions, so those
        stay apart.
      * A product the user took out of a family stays out.
    """
    units = _unit_counts(db, user_id)
    set_names = dict(
        db.query(models.CatalogProduct.id, models.CatalogProduct.set_name)
    )
    products = db.query(models.Product).filter(models.Product.user_id == user_id).all()

    buckets: dict[tuple[str, str], list[tuple[models.Product, dict]]] = defaultdict(list)
    for p in products:
        if not units.get(p.id) and p.family_id is None:
            continue
        set_name = set_names.get(p.catalog_product_id) if p.catalog_match_status == "confirmed" else None
        info = parse_product(p.canonical_name, set_name)
        if not info["variant"] and not info["kind"]:
            continue
        buckets[(_norm(info["set"] or ""), _norm(info["line"]))].append((p, info))

    grouped = 0
    for members in buckets.values():
        labels = [_norm(i["variant"] or i["kind"] or "") for _, i in members]
        if len(set(labels)) != len(labels):
            continue
        in_family = {p.family_id for p, _ in members if p.family_id}
        loose = [(p, i) for p, i in members if p.family_id is None and not p.family_opt_out]
        if len(in_family) == 1:
            family = db.get(models.ProductFamily, next(iter(in_family)))
            for p, info in loose:
                p.family_id = family.id
                p.variant_kind = info["kind"] or "specific"
                grouped += 1
        elif not in_family and len(loose) >= 2:
            loose.sort(key=lambda m: -units.get(m[0].id, 0))
            family = models.ProductFamily(user_id=user_id, name=loose[0][1]["base"])
            db.add(family)
            db.flush()
            for p, info in loose:
                p.family_id = family.id
                p.variant_kind = info["kind"] or "specific"
                grouped += 1
    if grouped:
        db.flush()
    return grouped


def _product(db: Session, user_id: str, product_id: str) -> models.Product:
    product = db.query(models.Product).filter_by(id=product_id, user_id=user_id).first()
    if product is None:
        raise ValueError("That product doesn't exist.")
    return product


def create_family(db: Session, user_id: str, name: str, members: list[dict]) -> models.ProductFamily:
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the item a name.")
    if len(members) < 2:
        raise ValueError("A family needs at least two versions.")
    products = []
    for m in members:
        product = _product(db, user_id, m["product_id"])
        if product.family_id is not None:
            raise ValueError(f"“{product.canonical_name}” is already in a family.")
        kind = m.get("variant_kind")
        if kind not in VARIANT_KINDS:
            raise ValueError("Each version must be specific or random.")
        products.append((product, kind))
    family = models.ProductFamily(user_id=user_id, name=name)
    db.add(family)
    db.flush()
    for product, kind in products:
        product.family_id = family.id
        product.variant_kind = kind
    return family


def get_family(db: Session, user_id: str, family_id: str) -> models.ProductFamily:
    family = db.query(models.ProductFamily).filter_by(id=family_id, user_id=user_id).first()
    if family is None:
        raise ValueError("That family doesn't exist.")
    return family


def members_of(db: Session, family: models.ProductFamily) -> list[models.Product]:
    return db.query(models.Product).filter_by(family_id=family.id).order_by(models.Product.canonical_name).all()


def ungroup(db: Session, family: models.ProductFamily, opt_out: bool = True) -> None:
    """Forget the grouping only -- products and units are untouched. By
    default the products are also kept out of automatic grouping."""
    for p in members_of(db, family):
        p.family_id = None
        p.variant_kind = None
        if opt_out:
            p.family_opt_out = True
    db.delete(family)


def add_member(db: Session, user_id: str, family: models.ProductFamily, product_id: str, kind: str) -> None:
    product = _product(db, user_id, product_id)
    if product.family_id is not None:
        raise ValueError(f"“{product.canonical_name}” is already in a family.")
    if kind not in VARIANT_KINDS:
        raise ValueError("A version must be specific or random.")
    product.family_id = family.id
    product.variant_kind = kind


def remove_member(db: Session, user_id: str, family: models.ProductFamily, product_id: str) -> bool:
    """Take one version out. A family of one makes no sense, so if only one
    would be left the whole family is dissolved; returns True when that
    happened."""
    product = _product(db, user_id, product_id)
    if product.family_id != family.id:
        raise ValueError("That product isn't in this family.")
    product.family_id = None
    product.variant_kind = None
    product.family_opt_out = True
    db.flush()
    if len(members_of(db, family)) < 2:
        ungroup(db, family, opt_out=False)
        return True
    return False


def update_family(db: Session, family: models.ProductFamily, fields: dict) -> None:
    """Rename, or set the type / category on EVERY version at once."""
    if fields.get("name") is not None and fields["name"].strip():
        family.name = fields["name"].strip()
    for key in ("product_type", "category"):
        if key in fields:
            for p in members_of(db, family):
                setattr(p, key, fields[key] or None)


def _stats(units) -> dict:
    sold = [(i, o) for i, o in units if i.status == "sold"]
    priced = [i for i, _ in sold if i.sold_price is not None]
    revenue = sum(i.sold_price for i in priced)
    cost = sum(i.cost_basis or 0 for i in priced)
    return {
        "units": len(units),
        "order_placed": sum(1 for i, _ in units if i.status == "not_shipped"),
        "in_transit": sum(1 for i, _ in units if i.status == "in_transit"),
        "in_hand": sum(1 for i, _ in units if i.status == "in_hand"),
        "sold": len(sold),
        "avg_cost": average_cost(units),
        "avg_sale_price": revenue / len(priced) if priced else None,
        "profit": revenue - cost if priced else None,
    }


def product_images(db: Session, product_ids: list[str]) -> dict[str, Optional[str]]:
    """One picture per product: its confirmed catalog image, else the most
    recent order's own thumbnail (Target / Pokémon Center listings)."""
    products = db.query(models.Product).filter(models.Product.id.in_(product_ids)).all()
    catalog = dict(
        db.query(models.CatalogProduct.id, models.CatalogProduct.image_url).filter(
            models.CatalogProduct.id.in_([p.catalog_product_id for p in products if p.catalog_product_id])
        )
    )
    thumbs: dict[str, str] = {}
    for pid, url in (
        db.query(models.Order.product_id, models.Order.thumbnail_url)
        .filter(models.Order.product_id.in_(product_ids), models.Order.thumbnail_url.isnot(None))
        .order_by(models.Order.purchased_at.asc())
        .all()
    ):
        thumbs[pid] = url  # later (newer) rows overwrite earlier ones
    return {
        p.id: (catalog.get(p.catalog_product_id) if p.catalog_match_status == "confirmed" else None) or thumbs.get(p.id)
        for p in products
    }


def family_dashboard(db: Session, user_id: str, family: models.ProductFamily) -> dict:
    members = members_of(db, family)
    all_units = units_for_products(db, user_id, [p.id for p in members])
    by_product: dict[str, list] = defaultdict(list)
    for item, order in all_units:
        by_product[item.product_id or (order.product_id if order else None)].append((item, order))

    variants = []
    for p in members:
        stats = _stats(by_product.get(p.id, []))
        variants.append(
            {
                "product_id": p.id,
                "name": p.canonical_name,
                "label": variant_label(p.canonical_name, p.variant_kind),
                "variant_kind": p.variant_kind,
                **stats,
            }
        )
    images = product_images(db, [p.id for p in members])
    by_label = {_norm(v["label"]): v for v in variants if v["variant_kind"] != "random"}
    for v in variants:
        v["image_url"] = images.get(v["product_id"])
        # A random pick could be any of the versions it names; show those.
        v["option_product_ids"] = []
        if v["variant_kind"] == "random":
            for option in random_options(v["label"]):
                hit = by_label.get(_norm(option))
                if hit:
                    v["option_product_ids"].append(hit["product_id"])
    for v in variants:
        v["option_image_urls"] = [
            u for pid in v["option_product_ids"] if (u := images.get(pid))
        ]
    variants.sort(key=lambda v: (-v["units"], v["label"]))

    totals = _stats(all_units)
    types = [p.product_type for p in members if p.product_type]
    cats = [p.category for p in members if p.category]
    candidates = (
        db.query(models.Product)
        .filter(models.Product.user_id == user_id, models.Product.family_id.is_(None))
        .order_by(models.Product.canonical_name)
        .all()
    )
    return {
        "family_id": family.id,
        "name": family.name,
        "product_type": Counter(types).most_common(1)[0][0] if types else None,
        "category": Counter(cats).most_common(1)[0][0] if cats else None,
        "total_units": totals["units"],
        "order_placed": totals["order_placed"],
        "in_transit": totals["in_transit"],
        "in_hand": totals["in_hand"],
        "sold": totals["sold"],
        "invested": sum(c for i, o in all_units if (c := original_cost(i, o)) is not None),
        "avg_cost": totals["avg_cost"],
        "variants": variants,
        "retailers": retailer_breakdown(all_units),
        "ungrouped_products": [{"product_id": p.id, "name": p.canonical_name} for p in candidates],
    }


def resolve_units(
    db: Session, user_id: str, source: models.Product, target: models.Product, quantity: int
) -> int:
    """
    Units of a random version that turned out to be a specific one -- you
    opened them and got Lucario. Moves `quantity` units from the random
    product to the specific one; each keeps its order, retailer and price.
    Units in hand go first, since those are the ones you can have opened.
    """
    if source.id == target.id:
        raise ValueError("Pick a different version to move them to.")
    if source.family_id is None or source.family_id != target.family_id:
        raise ValueError("Both versions must be in the same family.")
    if quantity < 1:
        raise ValueError("Move at least 1 unit.")
    movable = [(i, o) for i, o in units_for_products(db, user_id, [source.id]) if i.status != "sold"]
    movable.sort(key=lambda p: (_STAGE_ORDER.get(p[0].status, 9), p[0].created_at))
    if quantity > len(movable):
        raise ValueError(f"Only {len(movable)} unsold units to move.")
    for item, _ in movable[:quantity]:
        item.product_id = target.id
    return quantity
