from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .clock import app_today
from .config import settings
from .db import get_db
from .geo import haversine_km
from .lokero_models import FavoriteProductPreference
from .models import FavoriteProduct, MasterProduct, Offer, ProductAdminData, ProductCategory, Store
from .product_media import preferred_product_media
from .services import current_user

router = APIRouter(prefix="/api/lokero", tags=["lokero-media"])
MEDIA_DIR = settings.data_dir / "admin_media"

CATEGORY_ICONS = {
    "obst-gemuese": "apple",
    "fleisch-wurst": "beef",
    "fisch": "fish",
    "kaese": "cheese",
    "molkerei": "milk",
    "brot": "bread",
    "getraenke": "drink",
    "suesswaren": "candy",
    "tiefkuehl": "snow",
    "vorrat": "wheat",
    "fruehstueck": "coffee",
    "fertiggerichte": "soup",
    "drogerie": "sparkles",
    "haushalt": "home",
    "tiernahrung": "package",
    "sonstiges": "package",
}

# Conservative product-family hints. Alternatives are suggested only when the
# products share one of these families or a meaningful product-name token.
FAMILY_TERMS = (
    "cola", "wasser", "mineralwasser", "saft", "eistee", "bier", "wein",
    "gouda", "mozzarella", "feta", "camembert", "frischkäse",
    "milch", "joghurt", "quark", "butter", "margarine",
    "lachs", "thunfisch", "fischstäbchen",
    "hackfleisch", "hähnchenbrust", "schnitzel", "salami", "schinken",
    "toast", "brötchen", "baguette",
    "spaghetti", "nudeln", "reis", "kaffee",
    "chips", "schokolade", "toilettenpapier", "waschmittel",
    "katzenfutter", "hundefutter",
)
STOPWORDS = {
    "original", "classic", "klassik", "frisch", "frische", "mild", "natur",
    "premium", "bio", "extra", "sorten", "verschiedene", "stück", "packung",
    "gramm", "liter", "prozent", "angebot",
}


class FavoritePreferencePayload(BaseModel):
    allowAlternatives: bool


def _asset_is_serveable(asset) -> bool:
    if not asset:
        return False
    if asset.file_path:
        target = MEDIA_DIR / Path(asset.file_path).name
        if target.exists() and target.is_file():
            return True
    return bool(asset.source_url and asset.source_url.lower().startswith(("http://", "https://")))


def _category_slug(db: Session, product_id: int) -> str:
    meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product_id).first()
    if meta and meta.category and meta.category.active:
        return meta.category.slug
    return "sonstiges"


def _product_payload(db: Session, product: MasterProduct) -> dict:
    return {
        "id": str(product.id),
        "name": product.name,
        "brand": product.brand or "",
        "amount": product.package_size or "",
        "detail": product.package_size or "",
        "category": _category_slug(db, product.id),
        "ean": "",
        "tags": [],
        "imageUrl": f"/api/lokero/product-media/{product.id}",
    }


def _family(text: str) -> str | None:
    normalized = text.lower().replace("-", " ")
    for term in FAMILY_TERMS:
        if term in normalized:
            return term
    return None


def _tokens(text: str) -> set[str]:
    values = set(re.findall(r"[a-zäöüß]{4,}", text.lower()))
    return {value for value in values if value not in STOPWORDS}


def _similarity_reason(source: MasterProduct, candidate: MasterProduct) -> str | None:
    source_text = f"{source.brand or ''} {source.name}"
    candidate_text = f"{candidate.brand or ''} {candidate.name}"
    source_family = _family(source_text)
    candidate_family = _family(candidate_text)
    if source_family and source_family == candidate_family:
        return f"Gleiche Produktart: {source_family}"

    shared = _tokens(source.name) & _tokens(candidate.name)
    if shared:
        token = sorted(shared, key=len, reverse=True)[0]
        return f"Ähnliche Produktbezeichnung: {token}"
    return None


def _store_is_in_user_radius(user, store: Store) -> bool:
    if store.latitude is None or store.longitude is None:
        return False
    if user.latitude is None or user.longitude is None:
        return True
    return haversine_km(user.latitude, user.longitude, store.latitude, store.longitude) <= user.radius_km


@router.get("/product-media/{product_id}")
def product_media(product_id: int, db: Session = Depends(get_db)):
    asset = preferred_product_media(db, product_id, purpose="public")
    if not asset:
        raise HTTPException(status_code=404, detail="No product image")

    if asset.file_path:
        safe_name = Path(asset.file_path).name
        target = MEDIA_DIR / safe_name
        if target.exists() and target.is_file():
            return FileResponse(target, media_type=asset.mime_type or None)

    if asset.source_url and asset.source_url.lower().startswith(("http://", "https://")):
        return RedirectResponse(asset.source_url, status_code=307)

    raise HTTPException(status_code=404, detail="Product image unavailable")


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    rows = (
        db.query(
            ProductCategory.id,
            ProductCategory.name,
            ProductCategory.slug,
            ProductCategory.sort_order,
            func.count(ProductAdminData.id).label("product_count"),
        )
        .outerjoin(ProductAdminData, ProductAdminData.category_id == ProductCategory.id)
        .filter(ProductCategory.active.is_(True))
        .group_by(ProductCategory.id)
        .order_by(ProductCategory.sort_order.asc(), ProductCategory.name.asc())
        .all()
    )
    return [
        {
            "id": row.slug,
            "label": row.name,
            "icon": CATEGORY_ICONS.get(row.slug, "package"),
            "count": int(row.product_count or 0),
        }
        for row in rows
    ]


@router.get("/favorites/preferences")
def favorite_preferences(db: Session = Depends(get_db)):
    user = current_user(db)
    favorites = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id).all()
    pref_rows = db.query(FavoriteProductPreference).filter(FavoriteProductPreference.user_id == user.id).all()
    prefs = {row.master_product_id: bool(row.allow_alternatives) for row in pref_rows}
    return [
        {
            "productId": str(row.master_product_id),
            "allowAlternatives": prefs.get(row.master_product_id, False),
        }
        for row in favorites
    ]


@router.put("/favorites/products/{product_id}/preferences")
def update_favorite_preferences(
    product_id: int,
    payload: FavoritePreferencePayload,
    db: Session = Depends(get_db),
):
    user = current_user(db)
    favorite = (
        db.query(FavoriteProduct)
        .filter(FavoriteProduct.user_id == user.id, FavoriteProduct.master_product_id == product_id)
        .first()
    )
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite product not found")

    row = (
        db.query(FavoriteProductPreference)
        .filter(
            FavoriteProductPreference.user_id == user.id,
            FavoriteProductPreference.master_product_id == product_id,
        )
        .first()
    )
    if not row:
        row = FavoriteProductPreference(user_id=user.id, master_product_id=product_id)
        db.add(row)
    row.allow_alternatives = bool(payload.allowAlternatives)
    db.commit()
    return {"productId": str(product_id), "allowAlternatives": bool(row.allow_alternatives)}


@router.get("/favorites/products/{product_id}/alternatives")
def favorite_alternatives(product_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    favorite = (
        db.query(FavoriteProduct)
        .filter(FavoriteProduct.user_id == user.id, FavoriteProduct.master_product_id == product_id)
        .first()
    )
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite product not found")

    pref = (
        db.query(FavoriteProductPreference)
        .filter(
            FavoriteProductPreference.user_id == user.id,
            FavoriteProductPreference.master_product_id == product_id,
        )
        .first()
    )
    if not pref or not pref.allow_alternatives:
        return []

    source = favorite.product
    source_meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product_id).first()
    source_category_id = source_meta.category_id if source_meta else None
    if source_category_id is None:
        return []

    today = app_today()
    offers = (
        db.query(Offer)
        .join(Store, Store.id == Offer.store_id)
        .filter(
            Store.active.is_(True),
            Store.benchmark_verified.is_(True),
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= today,
            Offer.valid_to >= today,
            Offer.master_product_id != product_id,
        )
        .order_by(Offer.price.asc())
        .all()
    )

    best_by_product: dict[int, Offer] = {}
    for offer in offers:
        if not _store_is_in_user_radius(user, offer.store):
            continue
        meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == offer.master_product_id).first()
        if not meta or meta.category_id != source_category_id:
            continue
        reason = _similarity_reason(source, offer.product)
        if not reason:
            continue
        current = best_by_product.get(offer.master_product_id)
        if current is None or offer.price < current.price:
            best_by_product[offer.master_product_id] = offer

    result = []
    for offer in sorted(best_by_product.values(), key=lambda row: row.price)[:5]:
        reason = _similarity_reason(source, offer.product)
        result.append({
            "product": _product_payload(db, offer.product),
            "price": float(offer.price),
            "market": {
                "id": str(offer.store.id),
                "name": offer.store.name,
                "chain": offer.store.retailer,
            },
            "kind": "aehnlich",
            "reason": reason,
        })
    return result


@router.get("/media-coverage")
def media_coverage(db: Session = Depends(get_db)):
    """Report actually serveable image coverage for current public offers."""
    today = app_today()
    product_ids = [
        row[0]
        for row in (
            db.query(Offer.master_product_id)
            .join(Store, Store.id == Offer.store_id)
            .filter(
                Store.active.is_(True),
                Store.benchmark_verified.is_(True),
                Offer.valid_from <= today,
                Offer.valid_to >= today,
                Offer.local_store_offer.is_(True),
            )
            .distinct()
            .all()
        )
    ]

    with_media: list[int] = []
    missing: list[int] = []
    for product_id in product_ids:
        asset = preferred_product_media(db, product_id, purpose="public")
        if _asset_is_serveable(asset):
            with_media.append(product_id)
        else:
            missing.append(product_id)

    total = len(product_ids)
    covered = len(with_media)
    return {
        "currentPublicProducts": total,
        "withPublicMedia": covered,
        "missingPublicMedia": len(missing),
        "coveragePercentage": round((covered / total * 100.0), 1) if total else 100.0,
        "missingProductIds": missing[:200],
    }
