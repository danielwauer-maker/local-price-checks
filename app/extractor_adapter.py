from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata

from sqlalchemy.orm import Session

from .models import MasterProduct, Offer, Store
from .engine_v140.collectors import CollectedOffer
from .engine_v140.offer_quality import evaluate_offer
from .engine_v140.product_cleaning import clean_product_name
from .engine_v140.services import classify_offer


@dataclass(frozen=True)
class ImportSummary:
    received: int = 0
    imported: int = 0
    created_products: int = 0
    created_offers: int = 0
    updated_offers: int = 0
    rejected_online: int = 0
    rejected_quality: int = 0
    rejected_store: int = 0
    rejected_date: int = 0


def _ascii_fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def normalize_master_key(name: str, quantity: float | None = None, unit: str | None = None) -> str:
    """Conservative product identity used while no GTIN is available.

    It removes layout/origin noise and generic variant wording but deliberately
    keeps the actual product words and pack size. This reduces false merges
    across retailers while still allowing common prospect wording differences.
    """
    text = clean_product_name(name).lower()
    text = _ascii_fold(text)
    text = re.sub(r"\b(?:versch\.?|verschiedene)\s+sorten\b", " ", text)
    text = re.sub(r"\b(?:ursprung|herkunft)\s*:\s*[^,;]+", " ", text)
    text = re.sub(r"\b(?:kl\.?|klasse|handelsklasse)\s*[ivx]+\b", " ", text)
    text = re.sub(
        r"^(?:deutschland|niederlande|spanien|italien|frankreich|portugal|griechenland|osterreich)\s*[-–:]\s*",
        "",
        text,
    )
    text = re.sub(r"[^a-z0-9äöüß+]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if quantity is not None and unit:
        q = float(quantity)
        q_text = str(int(q)) if q.is_integer() else (f"{q:.3f}".rstrip("0").rstrip("."))
        u = unit.lower().replace("liter", "l").replace("stück", "st")
        text = f"{text}|{q_text}{u}"
    return text[:320]


def package_size_label(quantity: float | None, unit: str | None) -> str | None:
    if quantity is None or not unit:
        return None
    q = float(quantity)
    shown = str(int(q)) if q.is_integer() else str(q).replace(".", ",")
    return f"{shown} {unit}"


def _date(value: str | None):
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _find_store(db: Session, row: CollectedOffer) -> Store | None:
    store = db.query(Store).filter(Store.name == row.store_name).first()
    if store:
        return store
    # Do not silently map across chains merely because a name changed.
    return (
        db.query(Store)
        .filter(Store.retailer == row.retailer, Store.name.ilike(f"%{row.store_name}%"))
        .first()
    )


def import_collected_offers(db: Session, rows: list[CollectedOffer]) -> ImportSummary:
    counts = {
        "received": len(rows), "imported": 0, "created_products": 0,
        "created_offers": 0, "updated_offers": 0, "rejected_online": 0,
        "rejected_quality": 0, "rejected_store": 0, "rejected_date": 0,
    }

    for row in rows:
        local, _reason = classify_offer(row.source_text, row.source_url)
        if not row.local_store_offer or not local:
            counts["rejected_online"] += 1
            continue

        quality = evaluate_offer(row)
        if not quality.accepted:
            counts["rejected_quality"] += 1
            continue

        store = _find_store(db, row)
        if not store or store.retailer != row.retailer:
            counts["rejected_store"] += 1
            continue

        valid_from = _date(row.valid_from)
        valid_to = _date(row.valid_to)
        if not valid_from or not valid_to or valid_to < valid_from:
            counts["rejected_date"] += 1
            continue

        name = clean_product_name(row.product_name)
        key = normalize_master_key(name, row.quantity, row.unit)
        product = db.query(MasterProduct).filter(MasterProduct.normalized_key == key).first()
        if not product:
            product = MasterProduct(
                brand=None,
                name=name,
                package_size=package_size_label(row.quantity, row.unit),
                normalized_key=key,
            )
            db.add(product)
            db.flush()
            counts["created_products"] += 1

        offer = (
            db.query(Offer)
            .filter(
                Offer.store_id == store.id,
                Offer.master_product_id == product.id,
                Offer.valid_from == valid_from,
                Offer.price == float(row.price),
            )
            .first()
        )
        if not offer:
            offer = Offer(
                store_id=store.id,
                master_product_id=product.id,
                price=float(row.price),
                unit_price=row.unit_price,
                unit_price_unit=row.unit_price_unit,
                valid_from=valid_from,
                valid_to=valid_to,
                local_store_offer=True,
                source_url=row.source_url or None,
            )
            db.add(offer)
            counts["created_offers"] += 1
        else:
            offer.valid_to = valid_to
            offer.unit_price = row.unit_price
            offer.unit_price_unit = row.unit_price_unit
            offer.local_store_offer = True
            if row.source_url:
                offer.source_url = row.source_url
            counts["updated_offers"] += 1

        counts["imported"] += 1

    db.commit()
    return ImportSummary(**counts)
