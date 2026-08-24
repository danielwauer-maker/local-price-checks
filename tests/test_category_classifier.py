from app.category_classifier import infer_category_slug
from app.models import MasterProduct


def product(name: str, brand: str | None = None):
    return MasterProduct(name=name, brand=brand, package_size=None, normalized_key=name.lower())


def test_common_products_are_classified_into_store_like_categories():
    assert infer_category_slug(product("Buttercroissant Stück")) == "brot"
    assert infer_category_slug(product("Almighurt Erdbeere", "Ehrmann")) == "molkerei"
    assert infer_category_slug(product("Paprika Chips")) == "suesswaren"
    assert infer_category_slug(product("Premium Pils")) == "getraenke"
    assert infer_category_slug(product("Blumenkohl")) == "obst-gemuese"
    assert infer_category_slug(product("Junger Gouda 250 g")) == "kaese"
    assert infer_category_slug(product("ASC Lachsfilet 100 g")) == "fisch"


def test_live_rewe_regressions_are_classified_correctly():
    assert infer_category_slug(product("Knorr Fix Rahm-Champignons oder Fix Air Fryer Cheesy Blumenkohl")) == "fertiggerichte"
    assert infer_category_slug(product("Rheinfels Quelle Lemon")) == "getraenke"
    assert infer_category_slug(product("Sheba Katzennahrung")) == "tiernahrung"
    assert infer_category_slug(product("Schmackes Hell oder 0,0% Hell")) == "getraenke"
    assert infer_category_slug(product("Frischer Hähnchen-Schenkel")) == "fleisch-wurst"
    assert infer_category_slug(product("Müller Joghurt mit der Ecke")) == "molkerei"


def test_unknown_product_falls_back_to_sonstiges():
    assert infer_category_slug(product("Unbekannter Spezialartikel XYZ")) == "sonstiges"
