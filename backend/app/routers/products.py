"""
products.py (router)
--------------------
Product identity as an API: list what you hold grouped BY product, resolve
existing history into products, merge two products the matcher kept apart.

See app/products.py for why identity needs a real table rather than string
normalization.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import crud, models, products, schemas
from app.database import get_db

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[schemas.ProductOut])
def list_products(db: Session = Depends(get_db)):
    user = crud.get_or_create_default_user(db)
    rows = (
        db.query(models.Product)
        .filter_by(user_id=user.id)
        .order_by(models.Product.canonical_name)
        .all()
    )
    alias_counts = dict(
        db.query(models.ProductAlias.product_id, func.count(models.ProductAlias.id))
        .filter_by(user_id=user.id)
        .group_by(models.ProductAlias.product_id)
        .all()
    )
    return [
        schemas.ProductOut(
            id=p.id,
            canonical_name=p.canonical_name,
            normalized_key=p.normalized_key,
            category=p.category,
            alias_count=alias_counts.get(p.id, 0),
        )
        for p in rows
    ]


@router.get("/grouped", response_model=list[schemas.ProductGroup])
def grouped_inventory(db: Session = Depends(get_db)):
    """
    One row per product: how many units you hold, what they cost, and the
    status split. This is the view that makes "I have 12 of these" a fact
    the app can state instead of 12 identical-looking rows the user has to
    count by eye.

    A unit's product comes from its own product_id when it has one
    (standalone/imported stock) and otherwise from its order -- see
    InventoryItem.product_id for why it's stored in only one place.
    """
    user = crud.get_or_create_default_user(db)

    items = (
        db.query(models.InventoryItem, models.Order)
        .outerjoin(models.Order, models.InventoryItem.order_id == models.Order.id)
        .filter(models.InventoryItem.user_id == user.id)
        .filter(models.InventoryItem.deleted_at.is_(None))
        .all()
    )

    all_products = db.query(models.Product).filter_by(user_id=user.id).all()
    names = {p.id: p.canonical_name for p in all_products}
    categories = {p.id: p.category for p in all_products}

    catalog_images = dict(
        db.query(models.CatalogProduct.id, models.CatalogProduct.image_url)
    )
    # Product -> catalog image, for anything actually matched.
    product_catalog_image = {
        p.id: catalog_images.get(p.catalog_product_id)
        for p in all_products
        if p.catalog_match_status == "confirmed" and p.catalog_product_id
    }
    # Fallback: the most recent embed thumbnail among each product's own
    # orders -- covers everything a card catalog never will (sneakers,
    # apparel, Pokemon Center exclusives). Latest first() per product_id
    # via ORDER BY, so ties resolve to the most recent purchase.
    thumbnails = dict(
        db.query(models.Order.product_id, models.Order.thumbnail_url)
        .filter(models.Order.product_id.isnot(None), models.Order.thumbnail_url.isnot(None))
        .order_by(models.Order.purchased_at.desc())
        .all()
    )

    groups: dict[str, dict] = {}
    for item, order in items:
        product_id = item.product_id or (order.product_id if order else None)
        # No product_id doesn't mean "no name" -- a standalone item (manual
        # add, or a spreadsheet import's mode='unit' row) carries its own
        # product_text, and an order that was never matched to a Product
        # still has raw_product_text. Falling back to a single shared
        # "Unmatched" bucket keyed by nothing would silently merge every
        # DIFFERENT unmatched product into one indistinguishable row --
        # keying by the text itself instead keeps them apart, same as a
        # real product_id would.
        fallback_name = (item.product_text or (order.raw_product_text if order else None) or "Unmatched")
        key = product_id or f"__text__:{fallback_name.strip().lower()}"
        group = groups.setdefault(
            key,
            {
                "product_id": product_id,
                "name": names.get(product_id) if product_id else fallback_name,
                "category": categories.get(product_id) if product_id else None,
                "image_url": (
                    product_catalog_image.get(product_id) or thumbnails.get(product_id)
                    if product_id
                    else None
                ),
                "total_units": 0,
                "in_hand": 0,
                "listed": 0,
                "sold": 0,
                "total_cost_basis": 0.0,
                "total_sold_revenue": 0.0,
                "_priced_sale_count": 0,  # units sold WITH a recorded price
                "_sold_cost_basis": 0.0,  # cost basis of those SAME units, for profit
            },
        )
        group["total_units"] += 1
        if item.status in ("in_hand", "listed", "sold"):
            group[item.status] += 1
        group["total_cost_basis"] += item.cost_basis or 0
        if item.status == "sold":
            if item.sold_price is not None:
                group["total_sold_revenue"] += item.sold_price
                group["_priced_sale_count"] += 1
                group["_sold_cost_basis"] += item.cost_basis or 0

    results = []
    for g in groups.values():
        priced = g.pop("_priced_sale_count")
        sold_cost_basis = g.pop("_sold_cost_basis")
        g["avg_sale_price"] = g["total_sold_revenue"] / priced if priced else None
        g["total_profit"] = g["total_sold_revenue"] - sold_cost_basis if priced else None
        results.append(g)

    return [
        schemas.ProductGroup(**g)
        for g in sorted(results, key=lambda g: (-g["total_units"], g["name"] or ""))
    ]


@router.post("/rebuild", response_model=schemas.ProductRebuildResult)
def rebuild_products(db: Session = Depends(get_db)):
    """
    Resolve every order and standalone unit into a Product, and report how
    many merge suggestions fall out (without applying any of them -- see
    /products/suggestions).

    Safe to re-run: resolution is a lookup on an existing alias when one
    exists, so this converges rather than creating duplicates each time.
    That matters because it's also how improved matching rules get applied
    to history.
    """
    user = crud.get_or_create_default_user(db)

    orders = (
        db.query(models.Order)
        .filter_by(user_id=user.id)
        .filter(models.Order.raw_product_text.isnot(None))
        .all()
    )
    for order in orders:
        product = products.resolve_product(
            db, user.id, order.raw_product_text, category=order.category
        )
        if product:
            order.product_id = product.id
    db.commit()

    standalone = (
        db.query(models.InventoryItem)
        .filter_by(user_id=user.id, order_id=None)
        .filter(models.InventoryItem.deleted_at.is_(None))
        .filter(models.InventoryItem.product_text.isnot(None))
        .all()
    )
    for item in standalone:
        product = products.resolve_product(db, user.id, item.product_text)
        if product:
            item.product_id = product.id
    db.commit()

    return schemas.ProductRebuildResult(
        orders_resolved=len(orders),
        items_resolved=len(standalone),
        products=db.query(models.Product).filter_by(user_id=user.id).count(),
        suggestions=len(products.find_merge_suggestions(db, user.id)),
    )


@router.get("/suggestions", response_model=list[schemas.MergeSuggestion])
def merge_suggestions(db: Session = Depends(get_db)):
    """Pairs that are probably the same product, for the user to confirm.
    Never applied automatically -- see products.find_merge_suggestions for
    the real-data reason that restraint exists."""
    user = crud.get_or_create_default_user(db)
    return [schemas.MergeSuggestion(**s) for s in products.find_merge_suggestions(db, user.id)]


@router.post("/merge", response_model=schemas.BulkResult)
def merge(body: schemas.ProductMerge, db: Session = Depends(get_db)):
    user = crud.get_or_create_default_user(db)
    moved = products.merge_products(db, user.id, body.source_id, body.target_id)
    if moved == 0 and body.source_id == body.target_id:
        raise HTTPException(status_code=400, detail="Can't merge a product into itself.")
    return schemas.BulkResult(updated=moved)


@router.patch("/{product_id}", response_model=schemas.ProductOut)
def rename_product(
    product_id: str, body: schemas.ProductRename, db: Session = Depends(get_db)
):
    """Renaming changes only the DISPLAY name -- normalized_key (identity)
    is untouched, so renaming can never silently re-point existing rows."""
    user = crud.get_or_create_default_user(db)
    product = db.query(models.Product).filter_by(id=product_id, user_id=user.id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    product.canonical_name = body.canonical_name.strip() or product.canonical_name
    if body.category is not None:
        product.category = body.category or None
    db.commit()
    db.refresh(product)
    return schemas.ProductOut(
        id=product.id,
        canonical_name=product.canonical_name,
        normalized_key=product.normalized_key,
        category=product.category,
        alias_count=db.query(models.ProductAlias).filter_by(product_id=product.id).count(),
    )
