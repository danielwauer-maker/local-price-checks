from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session

from .models import AdminAuditLog, MasterProduct, ProductAdminData, ProductAlias


def audit(db: Session, action: str, entity_type: str, entity_id: str | int | None, details: str = "", actor: str = "admin"):
    db.add(AdminAuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None, details=details[:2000] if details else None))


def resolve_product_alias(db: Session, alias_key: str) -> MasterProduct | None:
    row = db.query(ProductAlias).filter(ProductAlias.alias_key == alias_key).first()
    return db.get(MasterProduct, row.master_product_id) if row else None


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


def apply_product_correction(db: Session, product: MasterProduct, *, name: str, brand: str | None, package_size: str | None, category_id: int | None, notes: str | None = None):
    old_name = product.name
    old_key = product.normalized_key
    remember_product_alias(db, old_key, product, "admin-correction")
    product.name = name.strip()
    product.brand = brand.strip() if brand and brand.strip() else None
    product.package_size = package_size.strip() if package_size and package_size.strip() else None
    meta = admin_data_for(db, product.id, create=True)
    meta.category_id = category_id
    meta.name_locked = True
    meta.category_locked = category_id is not None
    meta.notes = notes.strip() if notes and notes.strip() else None
    meta.updated_at = datetime.utcnow()
    audit(db, "product_corrected", "product", product.id, f"name: {old_name!r} -> {product.name!r}; alias={old_key}; category_id={category_id}")
