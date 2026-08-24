from app.admin_seed import DEFAULT_CATEGORIES, LEGACY_CATEGORY_SLUGS


def test_default_category_catalog_matches_final_lokero_taxonomy():
    slugs = [slug for _order, _name, slug in DEFAULT_CATEGORIES]
    assert slugs == [
        "obst-gemuese",
        "fleisch-wurst",
        "fisch",
        "kaese",
        "molkerei",
        "brot",
        "getraenke",
        "suesswaren",
        "tiefkuehl",
        "vorrat",
        "fruehstueck",
        "fertiggerichte",
        "drogerie",
        "haushalt",
        "tiernahrung",
        "sonstiges",
    ]


def test_legacy_broad_categories_are_retired():
    assert LEGACY_CATEGORY_SLUGS == {
        "molkerei-kuehlung",
        "fleisch-fisch",
        "backwaren",
        "suesswaren-snacks",
        "vorrat-grundnahrung",
        "haushalt-drogerie",
    }
