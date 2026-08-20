from types import SimpleNamespace

from app.engine_v140.source_registry import _normalize_edeka_market_url, source_for_store_record


def test_edeka_offer_and_prospect_routes_normalize_to_market_root():
    assert _normalize_edeka_market_url("https://www.edeka.de/maerkte/071378/angebote/") == "https://www.edeka.de/maerkte/071378/"
    assert _normalize_edeka_market_url("https://www.edeka.de/maerkte/071378/prospekte/") == "https://www.edeka.de/maerkte/071378/"


def test_auto_onboarded_edeka_source_uses_market_root():
    store = SimpleNamespace(
        id=77,
        name="EDEKA Neuer Markt",
        retailer="EDEKA",
        source_url="https://www.edeka.de/maerkte/123456/angebote/",
    )

    source = source_for_store_record(store)

    assert source is not None
    assert source.url == "https://www.edeka.de/maerkte/123456/"
    assert source.store_specific is True
