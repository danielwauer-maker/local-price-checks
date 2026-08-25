import pytest

from app.category_classifier import classify_product, infer_category_slug
from app.product_taxonomy import compound_head_matches, matching_family, normalize_search_text
from app.models import MasterProduct


def product(name: str, brand: str | None = None):
    return MasterProduct(name=name, brand=brand, package_size=None, normalized_key=name.lower())


def test_specific_cheese_fish_and_cola_rules_win():
    expected = {
        "Junger Gouda 250 g": "schnittkaese",
        "Büffel Mozzarella 125 g": "mozzarella",
        "ASC Lachsfilet 100 g": "fisch-produkte",
        "Thunfisch in eigenem Saft": "fischkonserven",
        "Iglo 15 Fischstäbchen": "fisch-paniert",
        "Coca-Cola Zero 1,25 l": "cola",
        "Pepsi Max": "cola",
        "Kräuter Frischkäse mit Milch": "frischkaese",
    }
    for name, category_slug in expected.items():
        assert infer_category_slug(product(name)) == category_slug


def test_common_live_products_use_specific_store_categories():
    expected = {
        "Buttercroissant Stück": "gebaeck",
        "Almighurt Erdbeere": "joghurt",
        "Paprika Chips": "chips",
        "Premium Pils": "bier",
        "Blumenkohl": "gemuese",
        "Knorr Fix Rahm-Champignons oder Fix Air Fryer Cheesy Blumenkohl": "instantgerichte",
        "Rheinfels Quelle Lemon": "wasser",
        "Sheba Katzennahrung": "katzenfutter",
        "Schmackes Hell oder 0,0% Hell": "bier",
        "Frischer Hähnchen-Schenkel": "gefluegel",
        "Müller Joghurt mit der Ecke": "joghurt",
    }
    for name, category_slug in expected.items():
        assert infer_category_slug(product(name)) == category_slug


def test_category_and_product_family_are_separate_results():
    result = classify_product(product("Junger Gouda"))
    assert result.category_slug == "schnittkaese"
    assert result.family_slug == "kaese"
    assert result.confidence == "high"


def test_unknown_product_is_not_forced_into_an_unrelated_category():
    result = classify_product(product("Unbekannter Spezialartikel XYZ"))
    assert result.category_slug == "sonstiges"
    assert result.confidence == "unknown"


def test_taxonomy_matching_rejects_embedded_short_words_and_keeps_real_tokens():
    expected = {
        "Rumpsteak": "fleisch",
        "Ginger Ale": "sonstiges",
        "Abwasserpumpe": "sonstiges",
        "Bierwurst": "wurst",
        "Weintrauben": "obst",
        "Gin": "spirituosen",
        "Rum": "spirituosen",
        "Rotwein": "wein",
        "Pils": "bier",
    }
    for name, category_slug in expected.items():
        assert infer_category_slug(product(name)) == category_slug


def test_product_family_matching_is_phrase_and_token_aware():
    assert matching_family("Rumpsteak") is None
    assert matching_family("Bierwurst") is None
    assert matching_family("Abwasserpumpe") is None
    assert matching_family("Coca-Cola").slug == "cola"
    assert matching_family("Pepsi").slug == "cola"


@pytest.mark.parametrize(
    ("name", "category_slug"),
    (
        ("Heinz Curry Mango Sauce", "saucen"),
        ("Corny Müsliriegel Milch Classic", "muesli"),
        ("Bresso Kräuter der Provence", "frischkaese"),
        ("Mirée Französische Kräuter", "frischkaese"),
        ("Knorr Salat Krönung", "saucen"),
        ("Dr. Oetker Ristorante Pizza/Bistro Flammkuchen Elsässer Art", "tiefkuehlpizza"),
        ("Ritter Sport Jamaica Rum Knusperstück", "schokolade"),
        ("Sensodyne ProSchmelz Zahnfleisch Plus", "zahnpflege"),
        ("Frosta Butter Chicken", "tiefkuehlgerichte"),
        ("Original Wagner Steinofen Pizza Salami", "tiefkuehlpizza"),
        ("LIKEMEAT Vegane Fleischalternative", "fleischersatz"),
        ("Planted Veganes Steak", "fleischersatz"),
        ("Vitakraft Menü mit Huhn", "tiernahrung"),
        ("SONDEY Jaffa Cake Orange XXL", "kekse"),
        ("MIKADO Schokostäbchen Milchschokolade", "schokolade"),
        ("Nadler Sahne Heringsfilets", "fisch-produkte"),
    ),
)
def test_production_reclassification_product_type_precedence(name, category_slug):
    result = classify_product(product(name))
    assert result.category_slug == category_slug
    assert result.confidence == "high"
    assert result.reason


def test_ingredient_only_fragment_remains_unknown_instead_of_becoming_fruit():
    result = classify_product(product("mit Zwiebel, Gurke und Apfel"))
    assert result.category_slug == "sonstiges"
    assert result.confidence == "unknown"
    assert "Zutatenliste" in result.reason


@pytest.mark.parametrize(
    "name",
    (
        "ASC Lachsfilets",
        "Matjesfilets nordische Art",
        "Pangasiusfilets",
        "Garnelen natur",
        "Rotbarschfilets",
    ),
)
def test_explicit_fish_product_terms_do_not_degrade_to_unknown(name):
    result = classify_product(product(name))
    assert result.category_slug in {
        "fisch-produkte",
        "raeucherfisch",
        "meeresfruechte",
    }
    assert result.confidence == "high"


@pytest.mark.parametrize(
    "name",
    (
        "Schafkäse natur",
        "Grillkäse Kräuter",
        "Käsescheiben mild",
        "Frischkäsecreme Gartenkräuter",
    ),
)
def test_explicit_cheese_product_terms_do_not_degrade_to_unknown(name):
    result = classify_product(product(name))
    assert result.category_slug in {
        "kaese",
        "schnittkaese",
        "hartkaese",
        "frischkaese",
        "feta-hirtenkaese",
    }
    assert result.confidence == "high"


@pytest.mark.parametrize(
    ("name", "category_slug"),
    (
        ("Zitronen", "obst"),
        ("Orangen", "obst"),
        ("Möhren", "gemuese"),
        ("Tomaten", "gemuese"),
        ("Zwiebeln", "gemuese"),
        ("Melonen", "obst"),
        ("Nektarinen", "obst"),
        ("Zwetschgen", "obst"),
        ("Champignons", "pilze"),
        ("Chicorée", "gemuese"),
    ),
)
def test_explicit_fruit_and_vegetable_products_are_recognized(name, category_slug):
    assert infer_category_slug(product(name)) == category_slug


@pytest.mark.parametrize(
    ("name", "category_slug"),
    (
        ("Krombacher Pilsener", "bier"),
        ("Paulaner Weißbier", "bier"),
        ("Mosel Riesling", "wein"),
        ("Grauburgunder trocken", "wein"),
        ("Sierra Tequila", "spirituosen"),
        ("Asbach Cognac", "spirituosen"),
    ),
)
def test_clear_alcohol_product_descriptions_are_recognized(name, category_slug):
    assert infer_category_slug(product(name)) == category_slug


@pytest.mark.parametrize(
    "name",
    (
        "Rügenwalder Vegane Mühlen Salami oder Veganer Schinken Spicker Mortadella",
        "Vegane Salami",
        "Veganer Schinken",
        "Vegetarische Bratwurst",
    ),
)
def test_vegan_or_vegetarian_context_blocks_later_meat_rules(name):
    result = classify_product(product(name))
    assert result.category_slug == "fleischersatz"
    assert result.confidence == "high"
    assert "Kontext verhindert" in result.reason


@pytest.mark.parametrize(
    ("name", "category_slug"),
    (
        ("Rumpsteak", "fleisch"),
        ("Schweine-Lachsbraten", "fleisch"),
        ("Kasseler Lachsbraten", "fleisch"),
        ("Frischer Hähnchen-Schenkel", "gefluegel"),
        ("Bierwurst", "wurst"),
        ("Schwarzwälder Schinken", "schinken"),
    ),
)
def test_real_meat_products_remain_meat_without_vegetarian_context(name, category_slug):
    assert infer_category_slug(product(name)) == category_slug


def test_kefir_uses_safe_general_dairy_category_and_never_sahne():
    result = classify_product(product("MILRAM Kefir Drink"))
    assert result.category_slug == "molkerei"
    assert result.category_slug != "sahne"
    assert result.reason == "Kefir als allgemeines Milchprodukt"


@pytest.mark.parametrize(
    "name",
    (
        "Original Wagner Steinofen Pizza Salami",
        "Gustavo Gusto Pizza Margherita",
        "Dr. Oetker Pizza Tradizionale Salame Romano",
        "Original Wagner Flammkuchen Elsässer Art",
    ),
)
def test_real_pizza_and_flammkuchen_products_keep_product_type_priority(name):
    assert infer_category_slug(product(name)) == "tiefkuehlpizza"


def test_pizza_token_does_not_turn_utensils_or_fleischkaese_into_pizza():
    utensil = classify_product(product("SILVERCREST Pizza-Backformen-Set"))
    assert utensil.category_slug == "sonstiges"
    assert utensil.confidence == "unknown"
    assert "Küchenutensil" in utensil.reason

    fleischkaese = classify_product(product("Pizza- oder Röstzwiebel-Fleischkäse"))
    assert fleischkaese.category_slug == "wurst"
    assert fleischkaese.category_slug != "tiefkuehlpizza"


@pytest.mark.parametrize(
    ("name", "category_slug"),
    (
        ("Corny Müsliriegel Schoko", "muesli"),
        ("Corny Müsliriegel Milch Classic", "muesli"),
        ("Müsliriegel Schokolade", "muesli"),
        ("Schokolade", "schokolade"),
        ("Milka Schokolade", "schokolade"),
        ("Müller Milch Reis", "molkerei-dessert"),
        ("Müller Milchreis", "molkerei-dessert"),
        ("High Protein Pudding", "molkerei-dessert"),
        ("Vollmilch", "milch"),
        ("Quarkbällchen", "gebaeck"),
        ("Quark-Bällchen", "gebaeck"),
        ("Quarkbällchen mit Zucker", "gebaeck"),
        ("Exquisa Quark", "quark"),
        ("Magerquark", "quark"),
        ("Tante Fanny Butter Blätterteig", "backzutaten"),
        ("Butter", "butter"),
        ("Kerrygold Irische Butter", "butter"),
    ),
)
def test_final_product_type_precedence_regressions(name, category_slug):
    assert infer_category_slug(product(name)) == category_slug


@pytest.mark.parametrize(
    ("name", "category_slug"),
    (
        ("Heinz Curry Mango Sauce", "saucen"),
        ("Bresso Kräuter der Provence", "frischkaese"),
        ("Mirée Französische Kräuter", "frischkaese"),
        ("Knorr Salat Krönung", "saucen"),
        ("Ritter Sport Jamaica Rum Knusperstück", "schokolade"),
        ("Sensodyne ProSchmelz Zahnfleisch Plus", "zahnpflege"),
        ("Frosta Butter Chicken", "tiefkuehlgerichte"),
        ("LIKEMEAT Vegane Fleischalternative", "fleischersatz"),
        ("Planted Veganes Steak", "fleischersatz"),
        ("Rügenwalder Vegane Mühlen Salami oder Veganer Schinken Spicker Mortadella", "fleischersatz"),
        ("Vitakraft Bonas Kaustangen mit Huhn XXL", "tiernahrung"),
        ("SONDEY Jaffa Cake Orange XXL", "kekse"),
        ("MIKADO Schokostäbchen Milchschokolade", "schokolade"),
        ("Nadler Sahne Heringsfilets", "fisch-produkte"),
        ("Schweine-Lachsbraten", "fleisch"),
        ("Kasseler Lachsbraten", "fleisch"),
        ("Bierwurst-Kugel", "wurst"),
        ("Coca-Cola", "cola"),
        ("Pepsi", "cola"),
        ("Weintrauben", "obst"),
        ("Kefir", "molkerei"),
    ),
)
def test_previously_fixed_production_cases_remain_stable(name, category_slug):
    assert infer_category_slug(product(name)) == category_slug


@pytest.mark.parametrize("name", ("Ginger Ale", "Abwasserpumpe"))
def test_previously_fixed_negative_cases_remain_unknown(name):
    result = classify_product(product(name))
    assert result.category_slug == "sonstiges"
    assert result.confidence == "unknown"


def test_ocr_hyphenation_is_rejoined_without_changing_normal_hyphen_tokens():
    assert normalize_search_text("Pizza-Back- formen-Set") == "pizza backformen set"
    assert normalize_search_text("Pizza-Back-\nformen-Set") == "pizza backformen set"
    assert normalize_search_text("Coca-Cola") == "coca cola"


@pytest.mark.parametrize(
    "name",
    (
        "SILVERCREST Pizza-Backformen-Set",
        "SILVERCREST Pizza-Back- formen-Set",
        "Pizza-Back form",
    ),
)
def test_pizza_utensils_with_ocr_variants_never_become_pizza(name):
    result = classify_product(product(name))
    assert result.category_slug == "sonstiges"
    assert result.confidence == "unknown"
    assert "Küchenutensil" in result.reason


@pytest.mark.parametrize("name", ("Pizza Margherita", "Steinofen Pizza Salami"))
def test_real_pizza_remains_pizza_after_ocr_normalization(name):
    assert infer_category_slug(product(name)) == "tiefkuehlpizza"


def test_gebratene_is_not_a_braten_compound_but_real_compounds_remain_valid():
    assert compound_head_matches("Gebratene", "braten") is False
    assert compound_head_matches("Lachsbraten", "braten") is True
    assert compound_head_matches("Rumpsteak", "steak") is True
    assert compound_head_matches("Bierwurst", "wurst") is True


@pytest.mark.parametrize(
    ("name", "brand"),
    (
        ("ASIA TASTE Gebratene Nudeln", None),
        ("Gebratene Nudeln", None),
        ("Gebratene Nudeln", "ASIA TASTE"),
    ),
)
def test_gebratene_nudeln_never_matches_fleisch(name, brand):
    result = classify_product(product(name, brand=brand))
    assert result.category_slug == "nudeln"
    assert result.category_slug != "fleisch"


@pytest.mark.parametrize(
    "name",
    ("Rumpsteak", "Schweine-Lachsbraten", "Kasseler Lachsbraten"),
)
def test_true_meat_compounds_survive_compound_boundary_hardening(name):
    assert infer_category_slug(product(name)) == "fleisch"
