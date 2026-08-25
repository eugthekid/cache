"""
catalog.py (router)
--------------------
Sync the external catalog, run matching, and let the user confirm or
reject the suggestions it can't apply automatically. See app/catalog.py
for why matching is split into auto-confirm vs. suggest-for-review.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import catalog, crud, models, schemas
from app.database import get_db

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.post("/sync", response_model=schemas.CatalogSyncResult)
def sync(body: schemas.CatalogSyncRequest, db: Session = Depends(get_db)):
    """
    Pulls the external catalog for one category into the local cache.
    Slow (walks every set) -- meant to be triggered explicitly from
    Settings, not on every page load.
    """
    try:
        result = catalog.sync_catalog(db, body.category)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Catalog sync failed: {exc}")
    return schemas.CatalogSyncResult(**result)


@router.post("/match", response_model=schemas.CatalogMatchResult)
def match(db: Session = Depends(get_db)):
    """Matches products against whatever's already in the local catalog
    cache. Safe to re-run -- confirmed products are skipped."""
    user = crud.get_or_create_default_user(db)
    result = catalog.find_catalog_matches(db, user.id)
    return schemas.CatalogMatchResult(**result)


@router.get("/suggestions", response_model=list[schemas.CatalogSuggestion])
def list_suggestions(db: Session = Depends(get_db)):
    user = crud.get_or_create_default_user(db)
    products = (
        db.query(models.Product)
        .filter_by(user_id=user.id, catalog_match_status="suggested")
        .all()
    )
    out = []
    for p in products:
        candidate = db.query(models.CatalogProduct).filter_by(id=p.catalog_product_id).first()
        if not candidate:
            continue
        out.append(
            schemas.CatalogSuggestion(
                product_id=p.id,
                our_name=p.canonical_name,
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_image_url=candidate.image_url,
                candidate_set=candidate.set_name,
            )
        )
    return out


@router.post("/suggestions/{product_id}/confirm", response_model=schemas.ProductOut)
def confirm_suggestion(
    product_id: str, body: schemas.CatalogConfirm, db: Session = Depends(get_db)
):
    """Approves a suggestion. `catalog_product_id` lets the user pick a
    different candidate than the one auto-suggested -- needed for
    assortment SKUs ("Styles May Vary") where several catalog products are
    all equally plausible until the box is actually opened."""
    user = crud.get_or_create_default_user(db)
    product = db.query(models.Product).filter_by(id=product_id, user_id=user.id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    catalog_product = db.query(models.CatalogProduct).filter_by(id=body.catalog_product_id).first()
    if catalog_product is None:
        raise HTTPException(status_code=404, detail="Catalog product not found")

    product.catalog_product_id = catalog_product.id
    product.catalog_match_status = "confirmed"
    product.catalog_rejected_id = None
    # A user-confirmed match should standardize the name too, same as an
    # auto-confirmed exact match does -- otherwise confirming just adds a
    # picture and leaves the messy retailer name in place.
    product.canonical_name = catalog_product.name
    db.commit()
    db.refresh(product)
    return schemas.ProductOut(
        id=product.id,
        canonical_name=product.canonical_name,
        normalized_key=product.normalized_key,
        category=product.category,
        alias_count=db.query(models.ProductAlias).filter_by(product_id=product.id).count(),
    )


@router.post("/suggestions/{product_id}/reject", response_model=schemas.BulkResult)
def reject_suggestion(product_id: str, db: Session = Depends(get_db)):
    """Declines the suggested candidate. Remembered via
    catalog_rejected_id so the next /catalog/match run won't re-suggest
    the same wrong candidate -- it may suggest a DIFFERENT one, or none."""
    user = crud.get_or_create_default_user(db)
    product = db.query(models.Product).filter_by(id=product_id, user_id=user.id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    product.catalog_rejected_id = product.catalog_product_id
    product.catalog_product_id = None
    product.catalog_match_status = "none"
    db.commit()
    return schemas.BulkResult(updated=1)


@router.get("/suggestions/{product_id}/candidates", response_model=list[schemas.CatalogCandidate])
def list_candidates(product_id: str, db: Session = Depends(get_db)):
    """
    All plausible catalog matches for one product, for the assortment case
    -- e.g. "30th Celebration Tin (Sylveon or Greninja) - Styles May Vary"
    is genuinely any of several catalog products until the box is opened,
    so the review UI needs to offer a real choice, not just one guess.
    """
    user = crud.get_or_create_default_user(db)
    product = db.query(models.Product).filter_by(id=product_id, user_id=user.id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    key = catalog.normalize_catalog_name(product.canonical_name)
    my_tokens = set(key.split())
    scored = []
    for c in db.query(models.CatalogProduct).all():
        score = catalog._token_similarity(my_tokens, set(c.normalized_key.split()))
        if score >= 0.3:
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return [
        schemas.CatalogCandidate(
            id=c.id, name=c.name, image_url=c.image_url, set_name=c.set_name, score=round(s, 2)
        )
        for s, c in scored[:8]
    ]
