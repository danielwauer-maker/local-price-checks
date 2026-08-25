from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .models import MasterProduct, ProductAdminData, ProductAlias, ProductCategory
from .product_taxonomy import (
    CATEGORY_BY_SLUG,
    PRODUCT_FAMILY_SPECS,
    matching_family,
    normalize_search_text,
)


@dataclass(frozen=True)
class ProductSearchMatch:
    product: MasterProduct
    category: ProductCategory | None
    family_slug: str | None
    rank: int


def _descendant_ids(categories: list[ProductCategory], root_ids: set[int]) -> set[int]:
    result = set(root_ids)
    changed = True
    while changed:
        changed = False
        for category in categories:
            if category.parent_id in result and category.id not in result:
                result.add(category.id)
                changed = True
    return result


def _ancestor_categories(
    category: ProductCategory | None,
    by_id: dict[int, ProductCategory],
) -> tuple[ProductCategory, ...]:
    result: list[ProductCategory] = []
    current = category
    while current is not None:
        result.append(current)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return tuple(result)


def _query_family(query: str):
    normalized = normalize_search_text(query)
    for family in PRODUCT_FAMILY_SPECS:
        if any(normalize_search_text(term) == normalized for term in family.terms):
            return family
    return None


def _query_category_ids(query: str, categories: list[ProductCategory]) -> tuple[set[int], set[int]]:
    normalized = normalize_search_text(query)
    direct: set[int] = set()
    for category in categories:
        spec = CATEGORY_BY_SLUG.get(category.slug)
        values = {normalize_search_text(category.name), normalize_search_text(category.slug)}
        if spec:
            values.update(normalize_search_text(term) for term in spec.search_terms)
        if normalized in values:
            direct.add(category.id)
    return direct, _descendant_ids(categories, direct)


def product_search_tokens(
    product: MasterProduct,
    category: ProductCategory | None,
    categories_by_id: dict[int, ProductCategory],
) -> set[str]:
    values = {
        normalize_search_text(product.name),
        normalize_search_text(product.brand),
        normalize_search_text(product.normalized_key),
    }
    ancestors = _ancestor_categories(category, categories_by_id)
    for ancestor in ancestors:
        values.add(normalize_search_text(ancestor.name))
        values.add(normalize_search_text(ancestor.slug))
        spec = CATEGORY_BY_SLUG.get(ancestor.slug)
        if spec:
            values.update(normalize_search_text(term) for term in spec.search_terms)
    family = matching_family(f"{product.brand or ''} {product.name}", category.slug if category else None)
    if family:
        values.add(normalize_search_text(family.label))
        values.update(normalize_search_text(term) for term in family.terms)
    return {value for value in values if value}


def search_products(
    db: Session,
    *,
    query: str = "",
    category_slug: str | None = None,
    limit: int = 50,
) -> list[ProductSearchMatch]:
    needle = query.strip()
    categories = db.query(ProductCategory).filter(ProductCategory.active.is_(True)).all()
    categories_by_id = {category.id: category for category in categories}
    categories_by_slug = {category.slug: category for category in categories}

    direct_category_ids, query_category_ids = _query_category_ids(needle, categories) if needle else (set(), set())
    filter_category_ids: set[int] = set()
    if category_slug:
        requested = categories_by_slug.get(category_slug)
        if requested:
            filter_category_ids = _descendant_ids(categories, {requested.id})
        else:
            return []

    family = _query_family(needle) if needle else None
    expanded_terms = {needle} if needle else set()
    if family:
        expanded_terms.update(family.terms)

    alias_ids: set[int] = set()
    if needle:
        alias_ids = {
            row.master_product_id
            for row in db.query(ProductAlias.master_product_id)
            .filter(ProductAlias.alias_key.ilike(f"%{needle}%"))
            .limit(250)
            .all()
        }

    candidate_query = (
        db.query(MasterProduct, ProductAdminData)
        .outerjoin(ProductAdminData, ProductAdminData.master_product_id == MasterProduct.id)
    )
    if filter_category_ids:
        candidate_query = candidate_query.filter(ProductAdminData.category_id.in_(filter_category_ids))
    if needle:
        conditions = []
        for term in sorted(expanded_terms):
            if term:
                pattern = f"%{term}%"
                conditions.extend((MasterProduct.name.ilike(pattern), MasterProduct.brand.ilike(pattern)))
        if query_category_ids:
            conditions.append(ProductAdminData.category_id.in_(query_category_ids))
        if alias_ids:
            conditions.append(MasterProduct.id.in_(alias_ids))
        candidate_query = candidate_query.filter(or_(*conditions))

    candidate_limit = max(limit * 10, 500) if needle else limit
    rows = candidate_query.order_by(MasterProduct.id).limit(candidate_limit).all()
    normalized_query = normalize_search_text(needle)
    matches: list[ProductSearchMatch] = []
    for product, meta in rows:
        category = categories_by_id.get(meta.category_id) if meta and meta.category_id else None
        normalized_name = normalize_search_text(product.name)
        normalized_brand = normalize_search_text(product.brand)
        candidate_family = matching_family(
            f"{product.brand or ''} {product.name}",
            category.slug if category else None,
        )
        ancestors = _ancestor_categories(category, categories_by_id)
        ancestor_ids = {row.id for row in ancestors}
        tokens = product_search_tokens(product, category, categories_by_id)

        if not needle:
            rank = 8
        elif normalized_name == normalized_query:
            rank = 0
        elif normalized_name.startswith(normalized_query):
            rank = 1
        elif normalized_query in normalized_name:
            rank = 2
        elif normalized_query and normalized_query in normalized_brand:
            rank = 3
        elif family and candidate_family and family.slug == candidate_family.slug:
            rank = 4
        elif direct_category_ids.intersection(ancestor_ids) and category and category.id in direct_category_ids:
            rank = 5
        elif direct_category_ids.intersection(ancestor_ids):
            rank = 6
        elif any(normalized_query in token for token in tokens):
            rank = 7
        else:
            continue
        matches.append(
            ProductSearchMatch(
                product,
                category,
                candidate_family.slug if candidate_family else None,
                rank,
            )
        )

    matches.sort(key=lambda match: (match.rank, normalize_search_text(match.product.name), match.product.id))
    return matches[:limit]
