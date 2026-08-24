from sqlalchemy.orm import Session

from .models import ProductCategory

DEFAULT_CATEGORIES = [
    (10, "Obst & Gemüse", "obst-gemuese"),
    (20, "Fleisch & Wurst", "fleisch-wurst"),
    (30, "Fisch & Meeresfrüchte", "fisch"),
    (40, "Käse", "kaese"),
    (50, "Milch & Molkerei", "molkerei"),
    (60, "Brot & Backwaren", "brot"),
    (70, "Getränke", "getraenke"),
    (80, "Süßwaren & Snacks", "suesswaren"),
    (90, "Tiefkühl", "tiefkuehl"),
    (100, "Vorrat", "vorrat"),
    (110, "Frühstück", "fruehstueck"),
    (120, "Fertiggerichte", "fertiggerichte"),
    (130, "Drogerie", "drogerie"),
    (140, "Haushalt", "haushalt"),
    (150, "Tiernahrung", "tiernahrung"),
    (999, "Sonstiges", "sonstiges"),
]

LEGACY_CATEGORY_SLUGS = {
    "molkerei-kuehlung",
    "fleisch-fisch",
    "backwaren",
    "suesswaren-snacks",
    "vorrat-grundnahrung",
    "haushalt-drogerie",
}


def seed_admin_catalog(db: Session):
    """Ensure the current Lokero taxonomy exists on old and new installations.

    This is additive: existing ids are preserved, while names/order for current
    slugs are normalized. Broad pre-Lokero categories are marked inactive so they
    no longer appear in public filters after unlocked products are reclassified.
    """
    by_slug = {row.slug: row for row in db.query(ProductCategory).all()}
    for sort_order, name, slug in DEFAULT_CATEGORIES:
        row = by_slug.get(slug)
        if row is None:
            row = ProductCategory(name=name, slug=slug, sort_order=sort_order, active=True)
            db.add(row)
            by_slug[slug] = row
        else:
            row.name = name
            row.sort_order = sort_order
            row.active = True

    for slug in LEGACY_CATEGORY_SLUGS:
        row = by_slug.get(slug)
        if row is not None:
            row.active = False

    db.commit()
