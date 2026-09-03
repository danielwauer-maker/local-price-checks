from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from .api_routes import _current_offer_rows, _market, _market_media_maps, _stores_for_bootstrap
from .db import get_db
from .models import (
    MasterProduct,
    OfferOccurrence,
    OfferPriceReference,
    ProductAdminData,
    ProductBarcode,
    ShoppingItem,
)
from .product_media import preferred_product_media_map
from .promotion_rules import parse_multibuy, promotion_payload
from .services import current_user, favorite_and_selected_store_ids

router = APIRouter(tags=["bootstrap"])


def _image_url(row) -> str | None:
    if row is None:
        return None
    return f"/media/{row.file_path}" if row.file_path else row.source_url


def _product_rows(db: Session, products: list[MasterProduct], barcode_by_product: dict[int, str]) -> list[dict]:
    product_ids = [row.id for row in products]
    if not product_ids:
        return []
    metadata_rows = (
        db.query(ProductAdminData)
        .options(joinedload(ProductAdminData.category))
        .filter(ProductAdminData.master_product_id.in_(product_ids))
        .all()
    )
    metadata_by_product = {row.master_product_id: row for row in metadata_rows}
    media_by_product = preferred_product_media_map(db, product_ids)
    result: list[dict] = []
    for product in products:
        meta = metadata_by_product.get(product.id)
        category = meta.category.name if meta and meta.category else "Sonstiges"
        result.append({
            "id": str(product.id),
            "name": product.name,
            "brand": product.brand or "",
            "category": category,
            "unit": product.package_size or "",
            "ean": barcode_by_product.get(product.id, ""),
            "emoji": "🏷️",
            "imageUrl": _image_url(media_by_product.get(product.id)),
        })
    return result


def _price_rows(db: Session, offers) -> list[dict]:
    offer_ids = [row.id for row in offers]
    if not offer_ids:
        return []
    references = {
        row.offer_id: row
        for row in db.query(OfferPriceReference).filter(OfferPriceReference.offer_id.in_(offer_ids)).all()
    }
    occurrences: dict[int, OfferOccurrence] = {}
    for row in (
        db.query(OfferOccurrence)
        .filter(OfferOccurrence.offer_id.in_(offer_ids))
        .order_by(OfferOccurrence.collected_at.desc(), OfferOccurrence.id.desc())
        .all()
    ):
        occurrences.setdefault(row.offer_id, row)

    result: list[dict] = []
    for offer in offers:
        reference = references.get(offer.id)
        occurrence = occurrences.get(offer.id)
        payload = {
            "productId": str(offer.master_product_id),
            "marketId": str(offer.store_id),
            "price": float(offer.price),
            "offer": {"price": float(offer.price), "until": offer.valid_to.strftime("%d.%m.")},
            "validFrom": offer.valid_from.isoformat(),
            "validTo": offer.valid_to.isoformat(),
            "unitPrice": float(offer.unit_price) if offer.unit_price is not None else None,
            "unitPriceUnit": offer.unit_price_unit,
            "referencePrice": float(reference.reference_price) if reference else None,
            "referenceType": reference.reference_type if reference else None,
            "referencePriceEstimated": bool(reference and reference.reference_type == "inferred_discount"),
            "discountPercent": float(reference.discount_percent) if reference and reference.discount_percent is not None else None,
            "promotion": None,
        }
        promotion = parse_multibuy(
            occurrence.source_text if occurrence else None,
            offer_price=float(offer.price),
            regular_price=float(reference.reference_price) if reference else None,
        )
        payload["promotion"] = promotion_payload(promotion)
        if promotion and promotion.valid and promotion.discount_percent is not None:
            payload["discountPercent"] = promotion.discount_percent
        result.append(payload)
    return result


@router.get("/api/bootstrap")
def optimized_bootstrap(db: Session = Depends(get_db)):
    user = current_user(db)
    favorite_ids, active_ids = favorite_and_selected_store_ids(db, user)
    stores = _stores_for_bootstrap(db, user, favorite_ids=favorite_ids)
    store_media, retailer_logos = _market_media_maps(db, stores)
    products = db.query(MasterProduct).order_by(MasterProduct.name).all()

    barcode_by_product: dict[int, str] = {}
    for row in db.query(ProductBarcode).all():
        barcode_by_product.setdefault(row.master_product_id, row.barcode)

    offers = _current_offer_rows(db, active_ids)
    basket_rows = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    basket = {str(row.master_product_id): float(row.quantity) for row in basket_rows}
    persistent = [str(store_id) for store_id in favorite_ids]

    return {
        "location": {
            "lat": user.latitude or 50.6199,
            "lng": user.longitude or 7.6264,
            "label": f"{user.postal_code or ''} {user.city or ''}".strip() or "Standort einrichten",
        },
        "radius": float(user.radius_km),
        "selected": persistent,
        "favorites": persistent,
        "activeSelected": [str(store_id) for store_id in active_ids],
        "basket": basket,
        "markets": [
            _market(
                db,
                store,
                image_url=store_media.get(store.id),
                logo_url=retailer_logos.get(store.retailer),
                preloaded=True,
            )
            for store in stores
        ],
        "products": _product_rows(db, products, barcode_by_product),
        "prices": _price_rows(db, offers),
    }
