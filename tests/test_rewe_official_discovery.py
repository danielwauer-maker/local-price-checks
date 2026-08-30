from types import SimpleNamespace

from app.engine_v140.source_registry import source_for_store_record
from app.retailer_store_sources import default_retailer_adapters, retailer_source_results


def test_rewe_official_source_returns_both_altenkirchen_markets():
    results = retailer_source_results("57610", default_retailer_adapters())
    rewe = next(result for result in results if result.retailer == "REWE")

    assert {store.external_id for store in rewe.stores} == {"8534500", "2500021"}
    assert {store.address for store in rewe.stores} == {"Bahnhofstr. 30", "Dammweg 10"}
    assert all(store.postal_code == "57610" for store in rewe.stores)
    assert all(store.source_url.startswith("https://www.rewe.de/marktseite/altenkirchen/") for store in rewe.stores)


def test_rewe_official_source_does_not_leak_altenkirchen_into_other_postcodes():
    results = retailer_source_results("56269", default_retailer_adapters())
    rewe = next(result for result in results if result.retailer == "REWE")

    assert {store.external_id for store in rewe.stores} == {"321019"}


def _store(*, store_id: int, name: str, external_id: str, source_url: str):
    return SimpleNamespace(
        id=store_id,
        retailer="REWE",
        name=name,
        external_id=external_id,
        source_url=source_url,
    )


def test_altenkirchen_bahnhofstr_market_page_becomes_offer_collection_page():
    source = source_for_store_record(
        _store(
            store_id=9,
            name="PETZ REWE Bahnhofstr. 30",
            external_id="8534500",
            source_url="https://www.rewe.de/marktseite/altenkirchen/8534500/petz-rewe-bahnhofstr-30/",
        )
    )

    assert source is not None
    assert source.store_specific is True
    assert source.url == "https://www.rewe.de/angebote/altenkirchen/8534500/petz-rewe-bahnhofstr-30/"


def test_altenkirchen_dammweg_market_page_becomes_offer_collection_page():
    source = source_for_store_record(
        _store(
            store_id=10,
            name="PETZ REWE Dammweg 10",
            external_id="2500021",
            source_url="https://www.rewe.de/marktseite/altenkirchen/2500021/petz-rewe-dammweg-10/",
        )
    )

    assert source is not None
    assert source.url == "https://www.rewe.de/angebote/altenkirchen/2500021/petz-rewe-dammweg-10/"


def test_hundertmark_keeps_existing_canonical_offer_collection_page():
    source = source_for_store_record(
        _store(
            store_id=1,
            name="REWE:XL Hundertmark",
            external_id="321019",
            source_url="https://www.rewe.de/marktseite/dierdorf/321019/rewe-xl-familie-hundertmark/",
        )
    )

    assert source is not None
    assert source.url == "https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/"
