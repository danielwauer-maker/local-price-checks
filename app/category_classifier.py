from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import MasterProduct, ProductAdminData, ProductCategory
from .product_taxonomy import (
    CLASSIFICATION_RULES,
    VEGETARIAN_MEAT_BLOCKED_SLUGS,
    compound_head_matches,
    ingredient_list_matches,
    matching_family,
    normalize_search_text,
    pizza_product_context_matches,
    pizza_utensil_context_matches,
    taxonomy_term_matches,
    vegetarian_context_matches,
)


@dataclass(frozen=True)
class ClassificationResult:
    category_slug: str
    family_slug: str | None
    reason: str
    confidence: str


@dataclass(frozen=True)
class ReclassificationEntry:
    product_id: int
    product_name: str
    old_category: str | None
    new_category: str
    reason: str
    status: str


@dataclass(frozen=True)
class ReclassificationSummary:
    inspected: int
    changed: int
    unchanged: int
    locked: int
    unknown: int
    entries: tuple[ReclassificationEntry, ...]


def classify_product(product: MasterProduct) -> ClassificationResult:
    haystack = normalize_search_text(" ".join(filter(None, (product.brand, product.name, product.package_size))))
    if ingredient_list_matches(product.name):
        return ClassificationResult(
            "sonstiges",
            None,
            "nur Zutatenliste erkannt; kein sicherer Produkttyp",
            "unknown",
        )
    if pizza_utensil_context_matches(haystack):
        return ClassificationResult(
            "sonstiges",
            None,
            "Pizza-Token beschreibt ein Küchenutensil, kein Lebensmittel",
            "unknown",
        )
    vegetarian_context = vegetarian_context_matches(haystack)
    for rule in CLASSIFICATION_RULES:
        matches = (
            any(taxonomy_term_matches(haystack, term) for term in rule.terms)
            or any(compound_head_matches(haystack, head) for head in rule.compound_heads)
            or (rule.slug == "tiefkuehlpizza" and pizza_product_context_matches(haystack))
        )
        if matches:
            if vegetarian_context and rule.slug in VEGETARIAN_MEAT_BLOCKED_SLUGS:
                return ClassificationResult(
                    "fleischersatz",
                    None,
                    f"veganer/vegetarischer Kontext verhindert {rule.slug}-Klassifikation",
                    "high",
                )
            family = matching_family(haystack, rule.slug)
            return ClassificationResult(rule.slug, family.slug if family else None, rule.reason, "high")
    return ClassificationResult("sonstiges", None, "keine sichere Taxonomie-Regel", "unknown")


def infer_category_slug(product: MasterProduct) -> str:
    """Compatibility wrapper used by collectors and existing callers."""

    return classify_product(product).category_slug


def ensure_auto_category(db: Session, product: MasterProduct, *, force_unlocked: bool = False) -> ProductAdminData:
    meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product.id).first()
    if meta and meta.category_locked:
        return meta
    if not meta:
        meta = ProductAdminData(master_product_id=product.id)
        db.add(meta)
        db.flush()

    if meta.category_id is not None and not force_unlocked:
        current = db.get(ProductCategory, meta.category_id)
        if current and current.slug != "sonstiges" and current.active:
            return meta

    result = classify_product(product)
    category = (
        db.query(ProductCategory)
        .filter(ProductCategory.slug == result.category_slug, ProductCategory.active.is_(True))
        .first()
    )
    if category:
        meta.category_id = category.id
    return meta


def reclassify_products(db: Session, *, apply: bool = False) -> ReclassificationSummary:
    category_rows = db.query(ProductCategory).filter(ProductCategory.active.is_(True)).all()
    categories = {row.slug: row for row in category_rows}
    categories_by_id = {row.id: row for row in category_rows}
    products = db.query(MasterProduct).order_by(MasterProduct.id).all()
    metadata = (
        {
            row.master_product_id: row
            for row in db.query(ProductAdminData)
            .filter(ProductAdminData.master_product_id.in_([product.id for product in products]))
            .all()
        }
        if products
        else {}
    )

    changed = unchanged = locked = unknown = 0
    entries: list[ReclassificationEntry] = []
    for product in products:
        meta = metadata.get(product.id)
        old = categories_by_id.get(meta.category_id) if meta and meta.category_id else None
        result = classify_product(product)
        target = categories.get(result.category_slug)
        if meta and meta.category_locked:
            locked += 1
            status = "locked"
        elif target is None or result.confidence == "unknown":
            unknown += 1
            status = "unknown"
        elif old and old.id == target.id:
            unchanged += 1
            status = "unchanged"
        else:
            changed += 1
            status = "changed"
            if apply:
                if meta is None:
                    meta = ProductAdminData(master_product_id=product.id)
                    db.add(meta)
                    metadata[product.id] = meta
                meta.category_id = target.id
        proposed_name = target.name if target else "Sonstiges"
        reason = result.reason
        if status == "unknown" and old and old.slug != "sonstiges":
            proposed_name = old.name
            reason = f"{reason}; bestehende plausible Kategorie {old.name!r} bleibt erhalten"
        entries.append(
            ReclassificationEntry(
                product.id,
                product.name,
                old.name if old else None,
                proposed_name,
                reason,
                status,
            )
        )
    if apply:
        db.commit()
    return ReclassificationSummary(len(products), changed, unchanged, locked, unknown, tuple(entries))


def backfill_auto_categories(db: Session, *, force_unlocked: bool = True) -> int:
    """Explicit compatibility API; callers must opt in to applying changes."""

    if not force_unlocked:
        return 0
    return reclassify_products(db, apply=True).changed
