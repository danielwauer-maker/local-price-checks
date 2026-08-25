from sqlalchemy.orm import Session

from .models import ProductCategory
from .product_taxonomy import PRODUCT_TAXONOMY

LEGACY_CATEGORY_SLUGS = {
    "molkerei-kuehlung",
    "fleisch-fisch",
    "backwaren",
    "suesswaren-snacks",
    "vorrat-grundnahrung",
    "vorrat",
    "haushalt-drogerie",
}


def seed_admin_catalog(db: Session):
    """Ensure the current Lokero taxonomy exists on old and new installations.

    Existing category ids are preserved. This matters on production databases,
    where ProductAdminData rows already reference the old ids.

    Some legacy categories used the *same display name* as a new Lokero category
    but a different slug (for example ``Süßwaren & Snacks``). Because both name
    and slug are unique, blindly inserting the new slug would fail at startup.
    In that case we migrate the existing row in place instead of inserting a
    duplicate, preserving all foreign-key references.
    """
    rows = db.query(ProductCategory).all()
    by_slug = {row.slug: row for row in rows}
    by_name = {row.name: row for row in rows}

    for spec in PRODUCT_TAXONOMY:
        sort_order, name, slug = spec.sort_order, spec.name, spec.slug
        row = by_slug.get(slug)

        # Production-safe legacy migration: reuse a row with the desired display
        # name if the target slug does not yet exist. This avoids violating the
        # UNIQUE constraint on product_categories.name and preserves its id.
        if row is None:
            row = by_name.get(name)
            if row is not None:
                old_slug = row.slug
                row.slug = slug
                if old_slug in by_slug and by_slug[old_slug] is row:
                    del by_slug[old_slug]
                by_slug[slug] = row
            else:
                row = ProductCategory(name=name, slug=slug, sort_order=sort_order, active=True)
                db.add(row)
                by_slug[slug] = row
                by_name[name] = row

        row.name = name
        row.sort_order = sort_order
        row.active = True

    db.flush()
    for spec in PRODUCT_TAXONOMY:
        row = by_slug[spec.slug]
        row.parent_id = by_slug[spec.parent_slug].id if spec.parent_slug else None

    for slug in LEGACY_CATEGORY_SLUGS:
        row = by_slug.get(slug)
        if row is not None:
            row.active = False

    db.commit()
