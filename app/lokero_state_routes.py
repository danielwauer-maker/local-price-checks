from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .clock import app_today
from .config import settings
from .db import get_db
from .feature_flags import feature_enabled
from .geo import haversine_km
from .lokero_models import FavoriteProductPreference
from .models import FavoriteProduct, MasterProduct, MediaAsset, Offer, ProductAdminData, ShoppingItem, Store
from .optimizer import optimize_shopping
from .product_taxonomy import matching_family, root_category_slug
from .routing import RoutingStop, optimized_roundtrip
from .services import current_user, selected_store_ids

router = APIRouter(prefix="/api/lokero", tags=["lokero-state"])
MEDIA_DIR = settings.data_dir / "admin_media"

_STOPWORDS = {"angebot", "angebote", "verschiedene", "sorten", "original", "classic", "klassik", "frisch", "frische", "premium", "extra", "stück", "packung", "gramm", "liter", "oder", "und", "mit", "von", "der", "die", "das", "des", "dem", "den"}


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9äöüß]{3,}", (value or "").lower()) if token not in _STOPWORDS}


def _category_slug(db: Session, product_id: int) -> str:
    meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product_id).first()
    if meta and meta.category and meta.category.active:
        return root_category_slug(meta.category.slug)
    return "sonstiges"


def _product_payload(db: Session, product: MasterProduct) -> dict:
    return {"id": str(product.id), "name": product.name, "brand": product.brand or "", "amount": product.package_size or "", "detail": product.package_size or "", "category": _category_slug(db, product.id), "ean": "", "tags": [], "imageUrl": f"/api/lokero/product-media/{product.id}"}


def _in_user_radius(user, store: Store) -> bool:
    if store.latitude is None or store.longitude is None:
        return False
    if user.latitude is None or user.longitude is None:
        return True
    return haversine_km(user.latitude, user.longitude, store.latitude, store.longitude) <= user.radius_km


def _similarity(source: MasterProduct, candidate: MasterProduct, source_category: str, candidate_category: str) -> tuple[float, str, str] | None:
    source_name = (source.name or "").strip().lower(); candidate_name = (candidate.name or "").strip().lower(); source_brand = (source.brand or "").strip().lower(); candidate_brand = (candidate.brand or "").strip().lower(); source_pack = (source.package_size or "").strip().lower(); candidate_pack = (candidate.package_size or "").strip().lower()
    source_family = matching_family(f"{source.brand or ''} {source.name}", source_category); candidate_family = matching_family(f"{candidate.brand or ''} {candidate.name}", candidate_category)
    same_family = bool(source_family and candidate_family and source_family.slug == candidate_family.slug); same_category = source_category == candidate_category and source_category != "sonstiges"
    if not same_family and not same_category: return None
    source_tokens = _tokens(f"{source.brand or ''} {source.name}"); candidate_tokens = _tokens(f"{candidate.brand or ''} {candidate.name}"); shared = source_tokens & candidate_tokens; union = source_tokens | candidate_tokens
    token_score = len(shared) / len(union) if union else 0.0; name_score = SequenceMatcher(None, source_name, candidate_name).ratio(); same_brand = bool(source_brand and candidate_brand and source_brand == candidate_brand); same_pack = bool(source_pack and candidate_pack and source_pack == candidate_pack)
    score = name_score * 0.38 + token_score * 0.32
    if same_family: score += 0.16
    elif same_category: score += 0.07
    if same_brand: score += 0.12
    if same_pack: score += 0.08
    if score < 0.46 or (not shared and not same_brand and name_score < 0.72): return None
    if same_brand and same_pack and name_score >= 0.78: kind, reason = "identisch", "Sehr ähnliche Bezeichnung, Marke und Packungsgröße"
    elif same_brand: kind, reason = "marke", f"Gleiche Marke{f' · ähnlich: {max(shared, key=len)}' if shared else ''}"
    elif same_family: kind, reason = "aehnlich", f"Gleiche Produktart: {source_family.label}"
    else: kind, reason = "aehnlich", (f"Ähnliche Produktbezeichnung: {max(shared, key=len)}" if shared else "Ähnliches Produkt")
    return score, kind, reason


def _alternative_rows(db: Session, user, product: MasterProduct, *, limit: int = 5) -> list[dict]:
    today = app_today(); selected = set(selected_store_ids(db, user))
    query = db.query(Offer).join(Store, Store.id == Offer.store_id).filter(Store.active.is_(True), Store.benchmark_verified.is_(True), Offer.local_store_offer.is_(True), Offer.valid_from <= today, Offer.valid_to >= today, Offer.master_product_id != product.id)
    if selected: query = query.filter(Offer.store_id.in_(selected))
    source_category = _category_slug(db, product.id); ranked: dict[int, tuple[float, Offer, str, str]] = {}
    for offer in query.order_by(Offer.price.asc()).all():
        if not _in_user_radius(user, offer.store): continue
        candidate_category = _category_slug(db, offer.master_product_id); match = _similarity(product, offer.product, source_category, candidate_category)
        if not match: continue
        score, kind, reason = match; current = ranked.get(offer.master_product_id)
        if current is None or score > current[0] + 0.001 or (abs(score - current[0]) <= 0.001 and offer.price < current[1].price): ranked[offer.master_product_id] = (score, offer, kind, reason)
    result = []
    for score, offer, kind, reason in sorted(ranked.values(), key=lambda row: (-row[0], row[1].price))[:limit]:
        result.append({"product": _product_payload(db, offer.product), "price": float(offer.price), "market": {"id": str(offer.store.id), "name": offer.store.name, "chain": offer.store.retailer}, "kind": kind, "reason": reason, "confidence": round(score, 3)})
    return result


@router.put("/favorites/products/{product_id}")
def add_favorite_product(product_id: int, db: Session = Depends(get_db)):
    if not feature_enabled(db, "favorites"): raise HTTPException(status_code=404, detail="Favorites disabled")
    user = current_user(db); product = db.get(MasterProduct, product_id)
    if not product: raise HTTPException(status_code=404, detail="Product not found")
    row = db.query(FavoriteProduct).filter_by(user_id=user.id, master_product_id=product_id).first()
    if not row: db.add(FavoriteProduct(user_id=user.id, master_product_id=product_id)); db.commit()
    return {"ok": True, "favorite": True, "productId": str(product_id)}


@router.delete("/favorites/products/{product_id}")
def remove_favorite_product(product_id: int, db: Session = Depends(get_db)):
    if not feature_enabled(db, "favorites"): raise HTTPException(status_code=404, detail="Favorites disabled")
    user = current_user(db); row = db.query(FavoriteProduct).filter_by(user_id=user.id, master_product_id=product_id).first()
    if row: db.delete(row); db.commit()
    return {"ok": True, "favorite": False, "productId": str(product_id)}


@router.get("/favorites/products/{product_id}/alternatives")
def favorite_product_alternatives(product_id: int, db: Session = Depends(get_db)):
    user = current_user(db); favorite = db.query(FavoriteProduct).filter_by(user_id=user.id, master_product_id=product_id).first()
    if not favorite: raise HTTPException(status_code=404, detail="Favorite product not found")
    pref = db.query(FavoriteProductPreference).filter_by(user_id=user.id, master_product_id=product_id).first()
    if not pref or not pref.allow_alternatives: return []
    return _alternative_rows(db, user, favorite.product)


@router.get("/list/products/{product_id}/alternatives")
def list_product_alternatives(product_id: int, db: Session = Depends(get_db)):
    user = current_user(db); product = db.get(MasterProduct, product_id)
    if not product: raise HTTPException(status_code=404, detail="Product not found")
    return _alternative_rows(db, user, product, limit=3)


@router.get("/optimized-route-details")
def optimized_route_details(db: Session = Depends(get_db)):
    user = current_user(db); items = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all(); plan = optimize_shopping(db, user, items, "current", max_stores=3)
    stores = [store for store in plan.stores if store.latitude is not None and store.longitude is not None]
    stops = [RoutingStop(str(store.id), float(store.latitude), float(store.longitude)) for store in stores]
    result = optimized_roundtrip(user.latitude, user.longitude, stops, base_url=settings.routing_base_url, timeout_seconds=settings.routing_timeout_seconds, fallback_distance_factor=settings.route_distance_factor)
    by_id = {str(store.id): store for store in stores}
    ordered_names = [by_id[key].name for key in result.order if key in by_id]
    return {"distanceKm": round(result.distance_km, 1), "order": list(result.order), "stopNames": ordered_names, "legsKm": [round(value, 1) for value in result.legs_km], "estimated": result.estimated, "source": result.source}


@router.get("/retailer-logo/{retailer}")
def retailer_logo(retailer: str, db: Session = Depends(get_db)):
    normalized = retailer.strip(); row = db.query(MediaAsset).filter(MediaAsset.kind == "retailer_logo", func.lower(MediaAsset.retailer) == normalized.lower(), MediaAsset.active.is_(True)).order_by(MediaAsset.is_primary.desc(), MediaAsset.created_at.desc()).first()
    if row is None: row = db.query(MediaAsset).filter(MediaAsset.kind == "store", MediaAsset.store_id.is_(None), func.lower(MediaAsset.retailer) == normalized.lower(), MediaAsset.active.is_(True)).order_by(MediaAsset.is_primary.desc(), MediaAsset.created_at.desc()).first()
    if not row: raise HTTPException(status_code=404, detail="No retailer logo")
    if row.file_path:
        target = MEDIA_DIR / Path(row.file_path).name
        if target.exists() and target.is_file(): return FileResponse(target, media_type=row.mime_type or None)
    if row.source_url and row.source_url.lower().startswith(("http://", "https://")): return RedirectResponse(row.source_url, status_code=307)
    raise HTTPException(status_code=404, detail="Retailer logo unavailable")
