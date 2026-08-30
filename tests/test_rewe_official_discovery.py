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
