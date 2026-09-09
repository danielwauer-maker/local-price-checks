from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Iterable
import unicodedata

from sqlalchemy.orm import Session

from .models import MasterProduct
from .product_catalog_models import MasterProductProfile


_PACKAGE = re.compile(
    r"^\s*(?:(?P<count>\d+)\s*[x×]\s*)?(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g|l|ml|cl|st(?:k|ück)?|stück|pack)\b",
    re.I,
)

_UNIT_ALIASES = {
    "kg": "kg",
    "g": "g",
    "l": "l",
    "ml": "ml",
    "cl": "cl",
    "st": "st",
    "stk": "st",
    "stück": "st",
    "pack": "pack",
}


@dataclass(frozen=True)
class PackageFacts:
    value: float | None = None
    unit: str | None = None
    count: int | None = None
    total_quantity: float | None = None
    comparison_unit: str | None = None


def parse_package_size(value: str | None) -> PackageFacts:
    """Parse conservative package facts from the legacy package label.

    Unknown/complex labels stay unknown. BR-1B prefers incomplete canonical
    metadata over inventing a quantity from promotional prose.
    """
    raw = (value or "").strip().casefold()
    match = _PACKAGE.match(raw)
    if not match:
        return PackageFacts()
    number = float(match.group("value").replace(",", "."))
    unit = _UNIT_ALIASES.get(match.group("unit").casefold())
    count = int(match.group("count")) if match.group("count") else None
    total = number * count if count else number
    comparison = "kg" if unit in {"kg", "g"} else "l" if unit in {"l", "ml", "cl"} else "st" if unit == "st" else unit
    return PackageFacts(value=number, unit=unit, count=count, total_quantity=total, comparison_unit=comparison)


def _fold_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9äöüß+]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:320]


def canonical_family_key(product: MasterProduct) -> str:
    """Stable package-independent key used only for canonical family grouping."""
    return _fold_key(" ".join(part for part in (product.brand, product.name) if part))


def ensure_master_product_profile(
    db: Session,
    product: MasterProduct,
    *,
    data_source: str = "legacy_backfill",
    confidence: float | None = None,
) -> MasterProductProfile:
    """Create/update the additive profile for one canonical MasterProduct."""
    profile = (
        db.query(MasterProductProfile)
        .filter(MasterProductProfile.master_product_id == product.id)
        .first()
    )
    package = parse_package_size(product.package_size)
    if profile is None:
        profile = MasterProductProfile(
            master_product_id=product.id,
            canonical_name=product.name,
            family_key=canonical_family_key(product),
            package_value=package.value,
            package_unit=package.unit,
            package_count=package.count,
            total_quantity=package.total_quantity,
            comparison_unit=package.comparison_unit,
            verification_status="unverified",
            confidence=max(0.0, min(float(confidence or 0.0), 1.0)),
            data_source=data_source[:80],
            properties_json="{}",
        )
        db.add(profile)
        db.flush()
        return profile

    # Only fill canonical gaps automatically. Verified/admin-curated profile
    # fields are never overwritten by recurring collectors.
    if profile.verification_status != "verified":
        profile.canonical_name = profile.canonical_name or product.name
        profile.family_key = profile.family_key or canonical_family_key(product)
        if profile.package_value is None and package.value is not None:
            profile.package_value = package.value
            profile.package_unit = package.unit
            profile.package_count = package.count
            profile.total_quantity = package.total_quantity
            profile.comparison_unit = package.comparison_unit
        if confidence is not None:
            profile.confidence = max(profile.confidence or 0.0, max(0.0, min(float(confidence), 1.0)))
        if profile.data_source == "legacy_backfill" and data_source:
            profile.data_source = data_source[:80]
    return profile


def backfill_master_product_profiles(db: Session, *, batch_size: int = 500) -> int:
    """Idempotently create missing profiles for all existing master products."""
    created = 0
    last_id = 0
    while True:
        rows = (
            db.query(MasterProduct)
            .filter(MasterProduct.id > last_id)
            .order_by(MasterProduct.id)
            .limit(batch_size)
            .all()
        )
        if not rows:
            break
        existing_ids = {
            product_id
            for (product_id,) in db.query(MasterProductProfile.master_product_id)
            .filter(MasterProductProfile.master_product_id.in_([row.id for row in rows]))
            .all()
        }
        for product in rows:
            if product.id not in existing_ids:
                ensure_master_product_profile(db, product)
                created += 1
        db.flush()
        last_id = rows[-1].id
    return created


def profile_completeness(profile: MasterProductProfile) -> float:
    """Return a stable 0..1 completeness score for catalog operations."""
    values: Iterable[object] = (
        profile.canonical_name,
        profile.family_key,
        profile.package_value,
        profile.package_unit,
        profile.comparison_unit,
        profile.manufacturer,
        profile.product_family,
    )
    present = sum(value not in (None, "") for value in values)
    return round(present / 7.0, 4)


def profile_snapshot(profile: MasterProductProfile) -> dict:
    try:
        properties = json.loads(profile.properties_json or "{}")
    except json.JSONDecodeError:
        properties = {}
    return {
        "canonicalName": profile.canonical_name,
        "manufacturer": profile.manufacturer,
        "productFamily": profile.product_family,
        "variantName": profile.variant_name,
        "familyKey": profile.family_key,
        "package": {
            "value": profile.package_value,
            "unit": profile.package_unit,
            "count": profile.package_count,
            "totalQuantity": profile.total_quantity,
            "comparisonUnit": profile.comparison_unit,
        },
        "verificationStatus": profile.verification_status,
        "confidence": profile.confidence,
        "dataSource": profile.data_source,
        "properties": properties,
        "completeness": profile_completeness(profile),
    }
