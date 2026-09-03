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
from .lokero_models import FavoriteProductFamily, FavoriteProductPreference
from .models import FavoriteProduct, MasterProduct, Offer, ProductAdminData, ProductCategory, Store
from .product_media import preferred_product_media
from .product_taxonomy import matching_family, public_product_families, root_category_slug
from .services import current_user

router = APIRouter(prefix="/api/lokero", tags=["lokero-media"])
MEDIA_DIR = settings.data_dir / "admin_media"
PRODUCT_MEDIA_CACHE = {"Cache-Control": "public, max-age=300, stale-while-revalidate=3600"}

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
    "nudeln-reis": "wheat",
    "kochen-wuerzen": "soup",
    "fruehstueck": "coffee",
    "fertiggerichte": "soup",
    "alkohol": "drink",
    "vegetarisch-vegan": "apple",
    "baby-kind": "package",
    "drogerie": "sparkles",
    "haushalt": "home",
    "tiernahrung": "package",
    "sonstiges": "package",
}

PRODUCT_FAMILIES = public_product_families()
FAMILY_BY_SLUG = {row["slug"]: row for row in PRODUCT_FAMILIES}

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
        return root_category_slug(meta.category.slug)
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


def _market_payload(user, store: Store) -> dict:
    distance = 0.0
    if None not in (user.latitude, user.longitude, store.latitude, store.longitude):
        distance = haversine_km(user.latitude, user.longitude, store.latitude, store.longitude)
    return {
        "id": str(store.id),
        "name": store.name,
        "chain": store.retailer,
        "street": store.address,
        "city": store.city,
        "lat": float(store.latitude or 0),
        "lng": float(store.longitude or 0),
        "openUntil": "",
        "isOpen": True,
        "distanceKm": round(distance, 1),
        "savingPotential": 0.0,
        "strength": "",
        "verified": bool(store.benchmark_verified),
    }


def _offer_view_payload(db: Session, user, offer: Offer) -> dict:
    base_price = None
    if offer.unit_price is not None:
        base_price = f"{float(offer.unit_price):.2f} €/{offer.unit_price_unit or ''}".replace(".", ",")
    return {
        "offerId": str(offer.id),
        "productId": str(offer.master_product_id),
        "marketId": str(offer.store_id),
        "price": float(offer.price),
        "oldPrice": None,
        "discount": None,
        "basePrice": base_price,
        "leafletPage": None,
        "validFrom": offer.valid_from.isoformat(),
        "validUntil": offer.valid_to.isoformat(),
        "product": _product_payload(db, offer.product),
        "market": _market_payload(user, offer.store),
    }


def _family(text: str) -> str | None:
    family = matching_family(text)
    return family.slug if family else None


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


def _matches_family(product: MasterProduct, family: dict, category_slug: str) -> bool:
    candidate = matching_family(f"{product.brand or ''} {product.name}", category_slug)
    return candidate is not None and candidate.slug == family["slug"]


@router.get("/product-media/{product_id}")
def product_media(product_id: int, db: Session = Depends(get_db)):
    asset = preferred_product_media(db, product_id, purpose="public")
    if not asset:
        raise HTTPException(status_code=404, detail="No product image")

    if asset.file_path:
        safe_name = Path(asset.file_path).name
        target = MEDIA_DIR / safe_name
        if target.exists() and target.is_file():
            return FileResponse(target, media_type=asset.mime_type or None, headers=PRODUCT_MEDIA_CACHE)

    if asset.source_url and asset.source_url.lower().startswith(("http://", "https://")):
        return RedirectResponse(asset.source_url, status_code=307, headers=PRODUCT_MEDIA_CACHE)

    raise HTTPException(status_code=404, detail="Product image unavailable")


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    rows = db.query(ProductCategory).filter(ProductCategory.active.is_(True)).all()
    by_id = {row.id: row for row in rows}
    counts = {row.id: 0 for row in rows}
    for category_id, product_count in (
        db.query(ProductAdminData.category_id, func.count(ProductAdminData.id))
        .filter(ProductAdminData.category_id.is_not(None))
        .group_by(ProductAdminData.category_id)
        .all()
    ):
        current = by_id.get(category_id)
        while current is not None:
            counts[current.id] += int(product_count)
            current = by_id.get(current.parent_id)
    roots = sorted(
        (row for row in rows if row.parent_id is None),
        key=lambda row: (row.sort_order, row.name, row.id),
    )
    return [
        {
            "id": row.slug,
            "label": row.name,
            "icon": CATEGORY_ICONS.get(row.slug, "package"),
            "count": counts[row.id],
        }
        for row in roots
    ]


@router.get("/product-families")
def product_families():
    return PRODUCT_FAMILIES


@router.get("/favorites/families")
def favorite_families(db: Session = Depends(get_db)):
    user = current_user(db)
    rows = db.query(FavoriteProductFamily).filter(FavoriteProductFamily.user_id == user.id).all()
    return [FAMILY_BY_SLUG[row.family_slug] for row in rows if row.family_slug in FAMILY_BY_SLUG]


@router.put("/favorites/families/{slug}")
def add_favorite_family(slug: str, db: Session = Depends(get_db)):
    family = FAMILY_BY_SLUG.get(slug)
    if not family:
        raise HTTPException(status_code=404, detail="Unknown product family")
    user = current_user(db)
    row = (
        db.query(FavoriteProductFamily)
        .filter(FavoriteProductFamily.user_id == user.id, FavoriteProductFamily.family_slug == slug)
        .first()
    )
    if not row:
        db.add(FavoriteProductFamily(user_id=user.id, family_slug=slug))
        db.commit()
    return family


@router.delete("/favorites/families/{slug}")
def remove_favorite_family(slug: str, db: Session = Depends(get_db)):
    user = current_user(db)
    row = (
        db.query(FavoriteProductFamily)
        .filter(FavoriteProductFamily.user_id == user.id, FavoriteProductFamily.family_slug == slug)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


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


@router.get("/favorites/matched-offers")
def matched_favorite_offers(db: Session = Depends(get_db)):
    user = current_user(db)
    favorite_ids = {
        row.master_product_id
        for row in db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id).all()
    }
    family_rows = db.query(FavoriteProductFamily).filter(FavoriteProductFamily.user_id == user.id).all()
    families = [FAMILY_BY_SLUG[row.family_slug] for row in family_rows if row.family_slug in FAMILY_BY_SLUG]
    if not favorite_ids and not families:
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
        )
        .order_by(Offer.price.asc())
        .all()
    )
    best_by_product: dict[int, Offer] = {}
    for offer in offers:
        if not _store_is_in_user_radius(user, offer.store):
            continue
        category = _category_slug(db, offer.master_product_id)
        matches = offer.master_product_id in favorite_ids or any(
            _matches_family(offer.product, family, category) for family in families
        )
        if not matches:
            continue
        current = best_by_product.get(offer.master_product_id)
        if current is None or offer.price < current.price:
            best_by_product[offer.master_product_id] = offer
    return [_offer_view_payload(db, user, offer) for offer in list(best_by_product.values())[:24]]


@router.get("/products/{product_id}/last-offer")
def last_product_offer(product_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    today = app_today()
    rows = (
        db.query(Offer)
        .join(Store, Store.id == Offer.store_id)
        .filter(
            Offer.master_product_id == product_id,
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= today,
            Store.active.is_(True),
            Store.benchmark_verified.is_(True),
        )
        .order_by(Offer.valid_to.desc(), Offer.valid_from.desc(), Offer.id.desc())
        .all()
    )
    offer = next((row for row in rows if _store_is_in_user_radius(user, row.store)), None)
    if not offer:
        return None
    return {
        "price": float(offer.price),
        "market": {
            "id": str(offer.store.id),
            "name": offer.store.name,
            "chain": offer.store.retailer,
        },
        "validFrom": offer.valid_from.isoformat(),
        "validUntil": offer.valid_to.isoformat(),
    }


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
