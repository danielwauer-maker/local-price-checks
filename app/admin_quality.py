from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from .models import MasterProduct, MediaAsset, ProductAdminData

SUSPICIOUS_PATTERNS = [
    r"\bkassenbon\b",
    r"\bqr[- ]?code\b",
    r"\bgewinnspiel\b",
    r"\bartikel\s+preis\b",
    r"\b(?:2er|3er|4er|5er)[- ]?set\b",
    r"^\d+(?:[.,]\d+)?\s*%\b",
    r"\bhochladen\b",
    r"\bscannen\b",
]


def _normalized_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9äöüß]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def build_quality_report(db: Session, limit: int = 100) -> dict:
    products = db.query(MasterProduct).order_by(MasterProduct.name).all()
    meta_by_product = {m.master_product_id: m for m in db.query(ProductAdminData).all()}
    image_product_ids = {
        row.master_product_id
        for row in db.query(MediaAsset).filter(
            MediaAsset.kind == "product",
            MediaAsset.active.is_(True),
            MediaAsset.master_product_id.is_not(None),
        ).all()
    }

    suspicious = []
    missing_category = []
    missing_image = []
    for product in products:
        lowered = product.name.lower()
        reasons = []
        for pattern in SUSPICIOUS_PATTERNS:
            if re.search(pattern, lowered, re.IGNORECASE):
                reasons.append(pattern)
        if len(product.name.strip()) < 3:
            reasons.append("Name sehr kurz")
        if len(product.name) > 120:
            reasons.append("Name ungewöhnlich lang")
        if reasons:
            suspicious.append((product, ", ".join(reasons[:3])))

        meta = meta_by_product.get(product.id)
        if not meta or not meta.category_id:
            missing_category.append(product)
        if product.id not in image_product_ids:
            missing_image.append(product)

    groups: dict[str, list[MasterProduct]] = defaultdict(list)
    for product in products:
        base = _normalized_name(product.name)
        if base:
            groups[base].append(product)

    duplicates = []
    seen_pairs: set[tuple[int, int]] = set()
    for same_name in groups.values():
        if len(same_name) > 1:
            first = same_name[0]
            for other in same_name[1:]:
                duplicates.append((first, other, 1.0))
                seen_pairs.add(tuple(sorted((first.id, other.id))))

    # Small fuzzy pass only among similarly-sized names. This is intentionally
    # conservative and review-only; it never merges products automatically.
    candidates = products[:500]
    for i, left in enumerate(candidates):
        ln = _normalized_name(left.name)
        if len(ln) < 8:
            continue
        for right in candidates[i + 1:]:
            pair = tuple(sorted((left.id, right.id)))
            if pair in seen_pairs:
                continue
            rn = _normalized_name(right.name)
            if abs(len(ln) - len(rn)) > 8:
                continue
            ratio = SequenceMatcher(None, ln, rn).ratio()
            if ratio >= 0.92:
                duplicates.append((left, right, ratio))
                seen_pairs.add(pair)
                if len(duplicates) >= limit:
                    break
        if len(duplicates) >= limit:
            break

    return {
        "suspicious": suspicious[:limit],
        "missing_category": missing_category[:limit],
        "missing_image": missing_image[:limit],
        "duplicates": duplicates[:limit],
        "counts": {
            "suspicious": len(suspicious),
            "missing_category": len(missing_category),
            "missing_image": len(missing_image),
            "duplicates": len(duplicates),
        },
    }
