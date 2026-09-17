from __future__ import annotations

from app.candidate_source_refresh import refresh_candidate_from_source
from app.coverage_models import StoreDiscoveryCandidate
from app.models import Store


OLD_ALDI_PDF = (
    "https://s7g10.scene7.com/is/content/aldi/"
    "ALDI_SUED_Umwelterklaerung-2024.pdf"
)
ALDI_ALTENKIRCHEN = (
    "https://filialen.aldi-sued.de/rheinland-pfalz/altenkirchen/"
    "koelner-strasse-30a"
)


def _aldi_store() -> Store:
    return Store(
        id=17,
        retailer="ALDI SÜD",
        name="ALDI SÜD Altenkirchen",
        address="Kölner Straße 30a",
        postal_code="57610",
        city="Altenkirchen",
        latitude=50.687,
        longitude=7.65,
        active=True,
        benchmark_verified=True,
        source_url=OLD_ALDI_PDF,
    )


def _promoted_candidate(store: Store) -> StoreDiscoveryCandidate:
    candidate = StoreDiscoveryCandidate(
        id=101,
        source="official:aldi_sued",
        source_url=OLD_ALDI_PDF,
        source_external_id=None,
        retailer="ALDI SÜD",
        name="ALDI SÜD Altenkirchen",
        address="Kölner Straße 30a",
        postal_code="57610",
        city="Altenkirchen",
        latitude=50.687,
        longitude=7.65,
        status="promoted",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        matched_store_id=store.id,
    )
    candidate.matched_store = store
    return candidate


def test_verified_promoted_aldi_candidate_refreshes_only_store_source_provenance():
    store = _aldi_store()
    candidate = _promoted_candidate(store)

    drift = refresh_candidate_from_source(
        candidate,
        {
            "source": "official:aldi_sued",
            "source_url": ALDI_ALTENKIRCHEN,
            "source_external_id": None,
            "retailer": "ALDI SÜD",
            "name": "ALDI SÜD Altenkirchen",
            "address": "Kölner Straße 30a",
            "postal_code": "57610",
            "city": "Altenkirchen",
            "latitude": 50.687,
            "longitude": 7.65,
        },
        reset_verification_on_identity_change=True,
    )

    assert drift is False
    assert candidate.source_url == ALDI_ALTENKIRCHEN
    assert store.source_url == ALDI_ALTENKIRCHEN
    assert store.name == "ALDI SÜD Altenkirchen"
    assert store.address == "Kölner Straße 30a"
    assert store.latitude == 50.687
    assert store.longitude == 7.65


def test_unrelated_official_candidate_url_cannot_become_store_provenance():
    store = _aldi_store()
    candidate = _promoted_candidate(store)

    drift = refresh_candidate_from_source(
        candidate,
        {"source_url": OLD_ALDI_PDF},
        reset_verification_on_identity_change=True,
    )

    assert drift is False
    assert candidate.source_url == OLD_ALDI_PDF
    assert store.source_url == OLD_ALDI_PDF


def test_identity_drift_blocks_store_source_sync_even_when_new_url_is_official():
    store = _aldi_store()
    candidate = _promoted_candidate(store)

    drift = refresh_candidate_from_source(
        candidate,
        {
            "source_url": ALDI_ALTENKIRCHEN,
            "address": "Andere Straße 99",
        },
        reset_verification_on_identity_change=True,
    )

    assert drift is True
    assert candidate.source_url == ALDI_ALTENKIRCHEN
    assert candidate.address == "Kölner Straße 30a"
    assert store.source_url == OLD_ALDI_PDF
    assert "[source-refresh-drift]" in (candidate.verification_note or "")


def test_unverified_or_unpromoted_candidate_cannot_update_store_source():
    store = _aldi_store()
    candidate = _promoted_candidate(store)
    candidate.status = "verified"

    refresh_candidate_from_source(
        candidate,
        {"source_url": ALDI_ALTENKIRCHEN},
        reset_verification_on_identity_change=True,
    )

    assert candidate.source_url == ALDI_ALTENKIRCHEN
    assert store.source_url == OLD_ALDI_PDF


def test_external_id_mismatch_blocks_store_source_sync():
    store = Store(
        id=9,
        retailer="REWE",
        name="REWE",
        address="Bahnhofstr. 30",
        postal_code="57610",
        city="Altenkirchen",
        external_id="8534500",
        source_url="https://www.rewe.de/angebote/",
    )
    candidate = StoreDiscoveryCandidate(
        id=102,
        source="official:rewe",
        source_url="https://www.rewe.de/marktseite/altenkirchen/9999999/falsch/",
        source_external_id="9999999",
        retailer="REWE",
        name="REWE",
        address="Bahnhofstr. 30",
        postal_code="57610",
        city="Altenkirchen",
        status="promoted",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        matched_store_id=store.id,
    )
    candidate.matched_store = store

    refresh_candidate_from_source(
        candidate,
        {"source_url": "https://www.rewe.de/marktseite/altenkirchen/9999999/falsch/"},
        reset_verification_on_identity_change=True,
    )

    assert store.source_url == "https://www.rewe.de/angebote/"
