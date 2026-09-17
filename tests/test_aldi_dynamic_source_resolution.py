from app.engine_v140.source_registry import source_for_store_record
from app.models import Store


ALDI_OFFERS_URL = "https://www.aldi-sued.de/angebote"
OLD_ALDI_IDENTITY_PDF = (
    "https://s7g10.scene7.com/is/content/aldi/ALDI_SUED_Umwelterklaerung-2024.pdf"
)
ALDI_ALTENKIRCHEN_BRANCH = (
    "https://www.aldi-sued.de/filialen/l/altenkirchen/koelner-strasse-30a/b496"
)


def _store(*, name: str, retailer: str, source_url: str | None, store_id: int = 17) -> Store:
    return Store(
        id=store_id,
        retailer=retailer,
        name=name,
        postal_code="57610",
        city="Altenkirchen",
        address="Kölner Straße 30a",
        latitude=50.687659,
        longitude=7.636920,
        active=False,
        benchmark_verified=False,
        source_url=source_url,
    )


def test_new_aldi_store_does_not_use_legacy_identity_pdf_as_collection_source():
    store = _store(
        name="ALDI SÜD Altenkirchen",
        retailer="ALDI SÜD",
        source_url=OLD_ALDI_IDENTITY_PDF,
    )

    source = source_for_store_record(store)

    assert source is not None
    assert source.url == ALDI_OFFERS_URL
    assert source.mode == "prospect_discovery"
    assert source.locality == "regional_chain"
    assert source.store_specific is False
    assert OLD_ALDI_IDENTITY_PDF not in source.url


def test_new_aldi_store_keeps_branch_identity_url_out_of_collection_source():
    store = _store(
        name="ALDI SÜD Altenkirchen",
        retailer="ALDI SÜD",
        source_url=ALDI_ALTENKIRCHEN_BRANCH,
    )

    source = source_for_store_record(store)

    assert source is not None
    assert source.url == ALDI_OFFERS_URL
    assert source.store_specific is False
    assert "Identitätsprovenienz" in source.notes


def test_known_aldi_market_keeps_curated_operational_source():
    store = _store(
        store_id=5,
        name="ALDI SÜD Dierdorf",
        retailer="ALDI SÜD",
        source_url=OLD_ALDI_IDENTITY_PDF,
    )

    source = source_for_store_record(store)

    assert source is not None
    assert source.key == "aldi_dierdorf"
    assert source.url == ALDI_OFFERS_URL
    assert source.locality == "regional_chain"
    assert source.store_specific is False


def test_non_aldi_dynamic_store_still_uses_store_specific_source():
    rewe_market_page = (
        "https://www.rewe.de/marktseite/altenkirchen/8534500/petz-rewe-bahnhofstr-30/"
    )
    store = _store(
        store_id=9,
        name="PETZ REWE Bahnhofstr. 30 Dynamic",
        retailer="REWE",
        source_url=rewe_market_page,
    )

    source = source_for_store_record(store)

    assert source is not None
    assert source.url == (
        "https://www.rewe.de/angebote/altenkirchen/8534500/petz-rewe-bahnhofstr-30/"
    )
    assert source.store_specific is True
    assert source.locality == "store_specific"
