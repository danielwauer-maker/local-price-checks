from app.admin_seed import LEGACY_CATEGORY_SLUGS
from app.product_taxonomy import PRODUCT_TAXONOMY


def test_default_category_catalog_matches_final_lokero_taxonomy():
    slugs = [category.slug for category in PRODUCT_TAXONOMY if category.parent_slug is None]
    assert slugs == [
        "obst-gemuese",
        "fleisch-wurst",
        "fisch",
        "kaese",
        "molkerei",
        "brot",
        "fruehstueck",
        "getraenke",
        "alkohol",
        "suesswaren",
        "tiefkuehl",
        "fertiggerichte",
        "nudeln-reis",
        "kochen-wuerzen",
        "vegetarisch-vegan",
        "baby-kind",
        "haushalt",
        "drogerie",
        "tiernahrung",
        "non-food",
        "sonstiges",
    ]


def test_legacy_broad_categories_are_retired():
    assert LEGACY_CATEGORY_SLUGS == {
        "molkerei-kuehlung",
        "fleisch-fisch",
        "backwaren",
        "suesswaren-snacks",
        "vorrat-grundnahrung",
        "vorrat",
        "haushalt-drogerie",
    }


def test_every_subcategory_references_an_existing_root_category():
    roots = {category.slug for category in PRODUCT_TAXONOMY if category.parent_slug is None}
    assert roots
    assert all(
        category.parent_slug in roots
        for category in PRODUCT_TAXONOMY
        if category.parent_slug is not None
    )
