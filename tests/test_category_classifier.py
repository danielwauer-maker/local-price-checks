import pytest

from app.category_classifier import classify_product, infer_category_slug
from app.product_taxonomy import matching_family
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
