from types import SimpleNamespace

from app.engine_v140.source_registry import source_for_store_record


def test_fellenzer_source_keeps_canonical_edeka_url_and_secondary_market_site():
    store = SimpleNamespace(
        id=7,
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        source_url=None,
    )

    source = source_for_store_record(store)

    assert source is not None
    assert source.url == "https://www.edeka.de/maerkte/071378/"
    assert source.alternate_urls == ("https://edeka-fellenzer.de/angebote/",)


def test_auto_edeka_source_has_no_invented_secondary_url():
    store = SimpleNamespace(
        id=99,
        retailer="EDEKA",
        name="EDEKA Beispiel",
        source_url="https://www.edeka.de/maerkte/123456/angebote/",
    )

    source = source_for_store_record(store)

    assert source is not None
    assert source.url == "https://www.edeka.de/maerkte/123456/"
    assert source.alternate_urls == ()
