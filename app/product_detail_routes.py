from __future__ import annotations

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .api_routes import _price_payload, _product
from .clock import app_today
from .db import get_db
from .models import MasterProduct, Offer
from .services import current_user, selected_store_ids

router = APIRouter(prefix="/api/products")

_DIMENSION_RE = re.compile(r"\b(\d{2,3})\s*[x×]\s*(\d{2,3})(?:\s*[x×]\s*\d{1,3})?\s*cm\b", re.I)


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def product_family_key(name: str) -> str:
    """Stable display grouping for obvious size variants.

    Variant rows stay separate MasterProducts/Offers for price calculations; the
    family key is only a UI/detail grouping layer.
    """
    text = _fold(name or "").lower()
    text = _DIMENSION_RE.sub(" ", text)
    text = re.sub(r"\b(?:groesse|größe)\s*[a-z0-9/-]+\b", " ", text)
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:220]


def variant_label(name: str) -> str:
    match = _DIMENSION_RE.search(name or "")
    if match:
        return match.group(0).replace("×", "x")
    return ""


def _current_prices(db: Session, product_id: int, store_ids: list[int]) -> list[dict]:
    if not store_ids:
        return []
    today = app_today()
    rows = (
        db.query(Offer)
        .filter(
            Offer.master_product_id == product_id,
            Offer.store_id.in_(store_ids),
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= today,
            Offer.valid_to >= today,
        )
        .order_by(Offer.price.asc())
        .all()
    )
    return [_price_payload(row) for row in rows]


@router.get("/{product_id}")
def product_detail(product_id: int, db: Session = Depends(get_db)):
    product = db.get(MasterProduct, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    family = product_family_key(product.name)
    candidates = db.query(MasterProduct).order_by(MasterProduct.name).all()
    members = [row for row in candidates if product_family_key(row.name) == family]
    if not members:
        members = [product]

    user = current_user(db)
    store_ids = selected_store_ids(db, user)
    variants = []
    for row in members:
        payload = _product(db, row)
        payload["variantLabel"] = variant_label(row.name)
        payload["prices"] = _current_prices(db, row.id, store_ids)
        variants.append(payload)

    return {
        "product": _product(db, product),
        "familyKey": family,
        "variantLabel": variant_label(product.name),
        "variants": variants,
    }
