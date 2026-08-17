from sqlalchemy.orm import Session

from .models import ProductCategory

DEFAULT_CATEGORIES = [
    (10, "Obst & Gemüse", "obst-gemuese"),
    (20, "Molkerei & Kühlung", "molkerei-kuehlung"),
    (30, "Fleisch & Fisch", "fleisch-fisch"),
    (40, "Getränke", "getraenke"),
    (50, "Backwaren", "backwaren"),
    (60, "Tiefkühl", "tiefkuehl"),
    (70, "Süßwaren & Snacks", "suesswaren-snacks"),
    (80, "Vorrat & Grundnahrung", "vorrat-grundnahrung"),
    (90, "Haushalt & Drogerie", "haushalt-drogerie"),
    (100, "Tiernahrung", "tiernahrung"),
    (999, "Sonstiges", "sonstiges"),
]


def seed_admin_catalog(db: Session):
    if db.query(ProductCategory).count() > 0:
        return
    for sort_order, name, slug in DEFAULT_CATEGORIES:
        db.add(ProductCategory(name=name, slug=slug, sort_order=sort_order, active=True))
    db.commit()
