from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from .models import MasterProduct, MediaAsset, Offer, ProductAdminData
from .prospect_models import OfferProvenance, ProspectArchive

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


def _coverage(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def build_prospect_provenance_report(db: Session, limit: int = 100) -> dict:
    """Measure how completely imported offers can be traced to a PDF and page.

    The denominator is the set of offers for the same market and exact validity
    window as the archived prospect. That makes missing provenance visible
    instead of only counting rows which already have a provenance link.
    """
    archives = (
        db.query(ProspectArchive)
        .order_by(ProspectArchive.valid_from.desc(), ProspectArchive.fetched_at.desc())
        .limit(limit)
        .all()
    )

    rows = []
    total_offers = 0
    total_linked = 0
    total_with_page = 0
    total_invalid_pages = 0

    for archive in archives:
        offer_query = db.query(Offer).filter(Offer.store_id == archive.store_id)
        if archive.valid_from is not None:
            offer_query = offer_query.filter(Offer.valid_from == archive.valid_from)
        if archive.valid_to is not None:
            offer_query = offer_query.filter(Offer.valid_to == archive.valid_to)
        offers = offer_query.all()
        offer_ids = {offer.id for offer in offers}

        provenance = (
            db.query(OfferProvenance)
            .filter(OfferProvenance.prospect_archive_id == archive.id)
            .all()
        )
        linked_offer_ids = {p.offer_id for p in provenance if p.offer_id in offer_ids}
        valid_page_offer_ids = {
            p.offer_id
            for p in provenance
            if p.offer_id in offer_ids and 1 <= p.prospect_page <= archive.page_count
        }
        invalid_pages = [
            p for p in provenance
            if p.offer_id in offer_ids and not (1 <= p.prospect_page <= archive.page_count)
        ]

        offer_count = len(offer_ids)
        linked_count = len(linked_offer_ids)
        page_count = len(valid_page_offer_ids)
        missing_page_count = max(0, offer_count - page_count)
        pdf_coverage = _coverage(linked_count, offer_count)
        page_coverage = _coverage(page_count, offer_count)

        if offer_count == 0:
            status = "no_offers"
        elif page_coverage >= 99.0 and not invalid_pages:
            status = "released"
        elif page_coverage >= 95.0 and not invalid_pages:
            status = "review"
        else:
            status = "blocked"

        rows.append(
            {
                "archive_id": archive.id,
                "store_id": archive.store_id,
                "store_name": archive.store.name,
                "retailer": archive.retailer,
                "period_key": archive.period_key,
                "valid_from": archive.valid_from,
                "valid_to": archive.valid_to,
                "page_count": archive.page_count,
                "offers_total": offer_count,
                "offers_with_pdf": linked_count,
                "offers_with_page": page_count,
                "offers_without_page": missing_page_count,
                "invalid_page_links": len(invalid_pages),
                "pdf_coverage_pct": pdf_coverage,
                "page_coverage_pct": page_coverage,
                "status": status,
                "pdf_sha256": archive.pdf_sha256,
                "source_url": archive.source_url,
            }
        )
        total_offers += offer_count
        total_linked += linked_count
        total_with_page += page_count
        total_invalid_pages += len(invalid_pages)

    return {
        "rows": rows,
        "counts": {
            "prospects": len(rows),
            "offers_total": total_offers,
            "offers_with_pdf": total_linked,
            "offers_with_page": total_with_page,
            "offers_without_page": max(0, total_offers - total_with_page),
            "invalid_page_links": total_invalid_pages,
        },
        "pdf_coverage_pct": _coverage(total_linked, total_offers),
        "page_coverage_pct": _coverage(total_with_page, total_offers),
        "target_pct": 99.0,
    }


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

    provenance = build_prospect_provenance_report(db, limit=limit)
    return {
        "suspicious": suspicious[:limit],
        "missing_category": missing_category[:limit],
        "missing_image": missing_image[:limit],
        "duplicates": duplicates[:limit],
        "provenance": provenance,
        "counts": {
            "suspicious": len(suspicious),
            "missing_category": len(missing_category),
            "missing_image": len(missing_image),
            "duplicates": len(duplicates),
            "offers_without_page": provenance["counts"]["offers_without_page"],
        },
    }
