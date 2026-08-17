from app.category_classifier import infer_category_slug
from app.models import MasterProduct


def product(name: str, brand: str | None = None):
    return MasterProduct(name=name, brand=brand, package_size=None, normalized_key=name.lower())


def test_common_products_are_classified():
    assert infer_category_slug(product("Buttercroissant Stück")) == "backwaren"
    assert infer_category_slug(product("Almighurt Erdbeere", "Ehrmann")) == "molkerei-kuehlung"
    assert infer_category_slug(product("Paprika Chips")) == "suesswaren-snacks"
    assert infer_category_slug(product("Premium Pils")) == "getraenke"
    assert infer_category_slug(product("Blumenkohl")) == "obst-gemuese"


def test_unknown_product_falls_back_to_sonstiges():
    assert infer_category_slug(product("Unbekannter Spezialartikel XYZ")) == "sonstiges"
