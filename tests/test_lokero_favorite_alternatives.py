from app.feature_flags import DEFAULT_FEATURE_FLAGS
from app.lokero_favorite_routes import _alternative_match, _family
from app.models import MasterProduct


def product(name: str, brand: str | None = None) -> MasterProduct:
    return MasterProduct(name=name, brand=brand, normalized_key=f"test-{name}-{brand or ''}")


def test_cola_favorite_matches_other_cola_but_not_water():
    coke = product("Coca-Cola Original", "Coca-Cola")
    pepsi = product("Pepsi Cola", "Pepsi")
    water = product("Mineralwasser Classic", "Gerolsteiner")

    assert _family(coke) == "cola"
    assert _alternative_match(coke, pepsi)[0] is True
    assert _alternative_match(coke, water)[0] is False


def test_specific_food_family_beats_broad_category_similarity():
    salmon = product("Räucherlachs", "Ostsee")
    tuna = product("Thunfisch in eigenem Saft", "Followfish")
    other_salmon = product("ASC Lachsfilet", "REWE")

    assert _alternative_match(salmon, other_salmon)[0] is True
    assert _alternative_match(salmon, tuna)[0] is False


def test_backed_product_alternatives_feature_is_enabled_by_default():
    assert DEFAULT_FEATURE_FLAGS["product_alternatives"] is True
