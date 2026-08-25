from __future__ import annotations

from datetime import datetime
import re
from sqlalchemy.orm import Session

from .models import AdminAuditLog, MasterProduct, ProductAdminData, ProductAlias, ProductCategory


def audit(db: Session, action: str, entity_type: str, entity_id: str | int | None, details: str = "", actor: str = "admin"):
    db.add(AdminAuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None, details=details[:2000] if details else None))


def resolve_product_alias(db: Session, alias_key: str) -> MasterProduct | None:
    row = db.query(ProductAlias).filter(ProductAlias.alias_key == alias_key).first()
    return db.get(MasterProduct, row.master_product_id) if row else None


_GENERIC_BRAND_WORDS = {
    "bio", "deutsche", "deutscher", "frische", "frischer", "frisches",
    "helle", "heller", "helles", "rote", "roter", "rotes", "feine",
    "frische-sieger", "aktion", "premium", "classic", "natur",
}


def learned_brand_candidates(db: Session) -> set[str]:
    candidates: set[str] = set()
    corrected = (
        db.query(MasterProduct.brand)
        .join(ProductAdminData, ProductAdminData.master_product_id == MasterProduct.id)
        .filter(ProductAdminData.name_locked.is_(True), MasterProduct.brand.is_not(None))
        .all()
    )
    candidates.update(str(brand).strip() for (brand,) in corrected if brand and str(brand).strip())
    aliased = (
        db.query(MasterProduct.brand)
        .join(ProductAlias, ProductAlias.master_product_id == MasterProduct.id)
        .filter(ProductAlias.source == "admin-correction", MasterProduct.brand.is_not(None))
        .all()
    )
    candidates.update(str(brand).strip() for (brand,) in aliased if brand and str(brand).strip())
    from .prospect_models import ProspectOfferReview

    reviewed = db.query(ProspectOfferReview.expected_brand).filter(
        ProspectOfferReview.expected_brand.is_not(None)
    ).all()
    candidates.update(str(brand).strip() for (brand,) in reviewed if brand and str(brand).strip())
    return candidates


def infer_learned_brand(
    db: Session,
    product_name: str,
    *,
    candidates: set[str] | None = None,
) -> str | None:
    """Infer only brands backed by an explicit admin learning signal.

    This deliberately is not a first-word heuristic. A candidate must already
    exist in an admin-corrected product/alias or an audited prospect review and
    must match the beginning of the new product name on a token boundary.
    """
    if candidates is None:
        candidates = learned_brand_candidates(db)

    name = re.sub(r"\s+", " ", product_name or "").strip()
    matches = []
    for brand in candidates:
        clean = re.sub(r"[®™]+", "", brand).strip()
        if not clean or clean.lower() in _GENERIC_BRAND_WORDS or len(clean) < 2:
            continue
        if re.match(rf"^{re.escape(clean)}(?:\b|\s|[-–:/])", name, re.I):
            matches.append(brand)
    return max(matches, key=len) if matches else None


def remember_product_alias(db: Session, alias_key: str, product: MasterProduct, source: str = "admin"):
    row = db.query(ProductAlias).filter(ProductAlias.alias_key == alias_key).first()
    if row:
        row.master_product_id = product.id
        row.source = source
    else:
        db.add(ProductAlias(alias_key=alias_key, master_product_id=product.id, source=source))


def admin_data_for(db: Session, product_id: int, create: bool = False) -> ProductAdminData | None:
    row = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product_id).first()
    if not row and create:
        row = ProductAdminData(master_product_id=product_id)
        db.add(row)
        db.flush()
    return row


def _category_label(db: Session, category_id: int | None) -> str:
    if category_id is None:
        return "–"
    category = db.get(ProductCategory, category_id)
    return category.name if category else f"#{category_id}"


def product_correction_history(db: Session, product_id: int, limit: int = 20) -> list[AdminAuditLog]:
    """Return the latest explicit admin corrections for one product."""
    return (
        db.query(AdminAuditLog)
        .filter(
            AdminAuditLog.entity_type == "product",
            AdminAuditLog.entity_id == str(product_id),
            AdminAuditLog.action.in_(("product_corrected", "product_category_corrected")),
        )
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .limit(limit)
        .all()
    )


def apply_product_correction(
    db: Session,
    product: MasterProduct,
    *,
    name: str,
    brand: str | None,
    package_size: str | None,
    category_id: int | None,
    notes: str | None = None,
    actor: str = "admin",
):
    """Apply an explicit admin correction and make it authoritative.

    Category assignments made here are always locked when a category is set.
    Reclassification therefore must not overwrite them. The old normalized key
    is retained as an admin-correction alias so later imports of the same
    observed product can resolve back to this manually curated master product.
    Every correction is also written to the audit log as human-review history.
    """
    old_name = product.name
    old_brand = product.brand
    old_package_size = product.package_size
    old_key = product.normalized_key
    meta = admin_data_for(db, product.id, create=True)
    old_category_id = meta.category_id
    old_category_locked = bool(meta.category_locked)

    if category_id is not None and db.get(ProductCategory, category_id) is None:
        raise ValueError(f"Unknown product category id: {category_id}")

    remember_product_alias(db, old_key, product, "admin-correction")
    product.name = name.strip()
    product.brand = brand.strip() if brand and brand.strip() else None
    product.package_size = package_size.strip() if package_size and package_size.strip() else None
    meta.category_id = category_id
    meta.name_locked = True
    meta.category_locked = category_id is not None
    meta.notes = notes.strip() if notes and notes.strip() else None
    meta.updated_at = datetime.utcnow()

    details = (
        f"name: {old_name!r} -> {product.name!r}; "
        f"brand: {old_brand!r} -> {product.brand!r}; "
        f"package_size: {old_package_size!r} -> {product.package_size!r}; "
        f"category: {_category_label(db, old_category_id)!r} -> {_category_label(db, category_id)!r}; "
        f"category_locked: {old_category_locked} -> {meta.category_locked}; "
        f"alias={old_key}; notes={meta.notes!r}"
    )
    audit(db, "product_corrected", "product", product.id, details, actor)


def apply_manual_category_correction(
    db: Session,
    product: MasterProduct,
    *,
    category_id: int | None,
    notes: str | None = None,
    actor: str = "admin",
) -> ProductAdminData:
    """Change only the category while preserving all other curated product data.

    A selected category is immediately locked. Clearing the category removes
    the lock so a future classifier/review may assign it again. This provides a
    safe human-in-the-loop path without teaching broad automatic rules from one
    correction.
    """
    if category_id is not None and db.get(ProductCategory, category_id) is None:
        raise ValueError(f"Unknown product category id: {category_id}")

    meta = admin_data_for(db, product.id, create=True)
    old_category_id = meta.category_id
    old_locked = bool(meta.category_locked)
    remember_product_alias(db, product.normalized_key, product, "admin-correction")

    meta.category_id = category_id
    meta.category_locked = category_id is not None
    if notes is not None:
        meta.notes = notes.strip() or None
    meta.updated_at = datetime.utcnow()

    details = (
        f"category: {_category_label(db, old_category_id)!r} -> {_category_label(db, category_id)!r}; "
        f"category_locked: {old_locked} -> {meta.category_locked}; "
        f"alias={product.normalized_key}; notes={meta.notes!r}"
    )
    audit(db, "product_category_corrected", "product", product.id, details, actor)
    return meta
