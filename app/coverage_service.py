from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .coverage_models import CoverageRegion
from .geo import haversine_km, resolve_center
from .models import Offer, Store

KNOWN_RETAILERS = {
    "rewe": "REWE",
    "rewe xl": "REWE",
    "netto marken-discount": "Netto Marken-Discount",
    "netto": "Netto Marken-Discount",
    "aldi süd": "ALDI SÜD",
    "aldi sued": "ALDI SÜD",
    "lidl": "Lidl",
    "edeka": "EDEKA",
    "penny": "PENNY",
}


def seed_initial_coverage(db: Session) -> None:
    """Create the existing Westerwald pilot area once on upgraded installs."""
    if db.query(CoverageRegion).count():
        return
    lat, lng = resolve_center("57614", "Steimel") or (50.6199, 7.6264)
    db.add(CoverageRegion(
        name="Westerwald – Steimel/Dierdorf",
        postal_code="57614",
        city="Steimel",
        center_lat=lat,
        center_lng=lng,
        radius_km=15.0,
        status="live",
        active=True,
        notes="Initiale Pilotregion; Nutzerangebote nur aus benchmark-verifizierten Märkten.",
    ))
    db.commit()


def normalize_retailer(name: str, brand: str = "") -> str | None:
    hay = (brand or name or "").strip().lower()
    for key, value in KNOWN_RETAILERS.items():
        if key in hay:
            return value
    return None


def region_center(postal_code: str, city: str) -> tuple[float, float]:
    center = resolve_center(postal_code, city)
    if not center:
        raise ValueError("Region konnte nicht geocodiert werden")
    return center


def stores_in_region(db: Session, region: CoverageRegion) -> list[Store]:
    stores = db.query(Store).filter(Store.active.is_(True)).all()
    return [
        store
        for store in stores
        if store.latitude is not None
        and store.longitude is not None
        and haversine_km(region.center_lat, region.center_lng, store.latitude, store.longitude) <= region.radius_km
    ]


def coverage_payload(db: Session, region: CoverageRegion) -> dict[str, Any]:
    stores = stores_in_region(db, region)
    verified = [store for store in stores if store.benchmark_verified]
    store_ids = [store.id for store in verified]
    current_offers = 0
    current_offer_rows = 0
    if store_ids:
        from .clock import app_today
        today = app_today()
        rows = db.query(Offer).filter(
            Offer.store_id.in_(store_ids),
            Offer.local_store_offer.is_(True),
            Offer.valid_from <= today,
            Offer.valid_to >= today,
        ).all()
        current_offer_rows = len(rows)
        # User-facing count: the same product/pack/price/validity available in
        # several branches is one distinct promotion, not one card per store.
        keys = {
            (
                row.master_product_id,
                float(row.price),
                float(row.unit_price) if row.unit_price is not None else None,
                row.unit_price_unit or None,
                row.valid_from,
                row.valid_to,
            )
            for row in rows
        }
        current_offers = len(keys)
    return {
        "id": region.id,
        "name": region.name,
        "postalCode": region.postal_code,
        "city": region.city,
        "lat": region.center_lat,
        "lng": region.center_lng,
        "radiusKm": region.radius_km,
        "status": region.status,
        "active": region.active,
        "stores": len(stores),
        "verifiedStores": len(verified),
        "currentOffers": current_offers,
        "currentOfferRows": current_offer_rows,
    }


def discover_supermarkets(region: CoverageRegion) -> list[dict[str, Any]]:
    """Discover supermarket candidates from OpenStreetMap/Overpass.

    Discovery is only an onboarding aid. Results start unverified and therefore
    cannot enter user offers until QA explicitly releases the market.
    """
    radius_m = int(max(1000, min(region.radius_km, 50.0)) * 1000)
    query = f'''[out:json][timeout:25];(
      node["shop"="supermarket"](around:{radius_m},{region.center_lat},{region.center_lng});
      way["shop"="supermarket"](around:{radius_m},{region.center_lat},{region.center_lng});
      relation["shop"="supermarket"](around:{radius_m},{region.center_lat},{region.center_lng});
    );out center tags;'''
    response = httpx.post(
        "https://overpass-api.de/api/interpreter",
        content=query.encode("utf-8"),
        headers={"User-Agent": "LocalPriceChecks/0.3 market-onboarding"},
        timeout=35,
    )
    response.raise_for_status()
    rows: list[dict[str, Any]] = []
    for element in response.json().get("elements", []):
        tags = element.get("tags") or {}
        name = (tags.get("name") or tags.get("brand") or "").strip()
        brand = (tags.get("brand") or "").strip()
        retailer = normalize_retailer(name, brand)
        if not retailer:
            continue
        lat = element.get("lat") or (element.get("center") or {}).get("lat")
        lng = element.get("lon") or (element.get("center") or {}).get("lon")
        if lat is None or lng is None:
            continue
        street = " ".join(x for x in [tags.get("addr:street"), tags.get("addr:housenumber")] if x).strip()
        rows.append({
            "retailer": retailer,
            "name": name or retailer,
            "postal_code": tags.get("addr:postcode") or "",
            "city": tags.get("addr:city") or region.city or "",
            "address": street or "Adresse aus OSM nicht verfügbar",
            "latitude": float(lat),
            "longitude": float(lng),
            "external_id": tags.get("ref") or tags.get("ref:shop") or None,
            "source_url": tags.get("website") or tags.get("contact:website") or None,
        })
    return rows


def upsert_discovered_stores(db: Session, region: CoverageRegion) -> tuple[int, int]:
    created = 0
    matched = 0
    for item in discover_supermarkets(region):
        existing = None
        for candidate in db.query(Store).filter(Store.retailer == item["retailer"]).all():
            if candidate.latitude is None or candidate.longitude is None:
                continue
            if haversine_km(candidate.latitude, candidate.longitude, item["latitude"], item["longitude"]) < 0.15:
                existing = candidate
                break
        if existing:
            matched += 1
            if not existing.source_url and item["source_url"]:
                existing.source_url = item["source_url"]
            if not existing.external_id and item["external_id"]:
                existing.external_id = item["external_id"]
            continue
        base_name = item["name"]
        name = base_name
        suffix = 2
        while db.query(Store).filter(Store.name == name).first():
            name = f"{base_name} ({suffix})"
            suffix += 1
        db.add(Store(
            retailer=item["retailer"],
            name=name,
            postal_code=item["postal_code"] or (region.postal_code or ""),
            city=item["city"] or (region.city or ""),
            address=item["address"],
            latitude=item["latitude"],
            longitude=item["longitude"],
            active=True,
            benchmark_verified=False,
            external_id=item["external_id"],
            source_url=item["source_url"],
        ))
        created += 1
    region.updated_at = datetime.utcnow()
    db.commit()
    return created, matched
