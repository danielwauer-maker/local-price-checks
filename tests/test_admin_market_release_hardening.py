from app.admin_candidate_coordinate_routes import _coordinate_review_rows
from app.admin_coverage_routes import _activation_reconciliation
from app.coverage_models import StoreDiscoveryCandidate
from app.models import Store


def _candidate(candidate_id: int, key: str, retailer: str, address: str, *, source: str = "osm", **overrides):
    values = {
        "id": candidate_id,
        "discovery_key": key,
        "postal_code": "56587",
        "retailer": retailer,
        "name": f"{retailer} Testmarkt",
        "address": address,
        "city": "Oberhonnefeld-Gierend",
        "latitude": 50.55 + candidate_id / 10000,
        "longitude": 7.52 + candidate_id / 10000,
        "source": source,
        "address_verified": False,
        "coordinates_verified": False,
        "official_source_verified": False,
        "status": "discovered",
    }
    values.update(overrides)
    return StoreDiscoveryCandidate(**values)


def _store(store_id: int, retailer: str, address: str) -> Store:
    return Store(
        id=store_id,
        retailer=retailer,
        name=f"{retailer} Store",
        postal_code="56587",
        city="Oberhonnefeld-Gierend",
        address=address,
        latitude=50.55 + store_id / 10000,
        longitude=7.52 + store_id / 10000,
        active=False,
        benchmark_verified=False,
    )


def test_coordinate_queue_collapses_sources_to_one_ready_physical_market():
    official = _candidate(
        1,
        "official-edeka",
        "EDEKA",
        "Über dem Stellweg 5",
        source="official:edeka",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="verified",
    )
    osm = _candidate(
        2,
        "osm-edeka",
        "EDEKA",
        "Über dem Stellweg 5",
        source="osm",
    )

    open_rows, ready_rows = _coordinate_review_rows([osm, official])

    assert open_rows == []
    assert len(ready_rows) == 1
    assert ready_rows[0]["retailer"] == "EDEKA"
    assert ready_rows[0]["source_count"] == 2
    assert ready_rows[0]["address_verified"] is True
    assert ready_rows[0]["coordinates_verified"] is True


def test_coordinate_queue_cannot_show_one_physical_market_as_open_and_ready():
    official = _candidate(
        10,
        "official-lidl",
        "Lidl",
        "Urbacher Straße 31a",
        source="official:lidl",
        official_source_verified=True,
    )
    osm = _candidate(
        11,
        "osm-lidl",
        "Lidl",
        "Urbacher Straße 31a",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="verified",
    )

    open_rows, ready_rows = _coordinate_review_rows([official, osm])

    assert len(open_rows) + len(ready_rows) == 1
    assert len(ready_rows) == 1


def test_activation_reconciliation_shows_unpromoted_physical_market_and_orphan_store():
    edeka = _candidate(
        21,
        "edeka-promoted",
        "EDEKA",
        "Über dem Stellweg 5",
        source="official:edeka",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="promoted",
        matched_store_id=101,
    )
    aldi = _candidate(
        22,
        "aldi-ready",
        "ALDI SÜD",
        "Über dem Stellweg 22",
        source="official:aldi",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="verified",
    )
    linked_store = _store(101, "EDEKA", "Über dem Stellweg 5")
    orphan_store = _store(999, "PENNY", "Westerwaldstraße 6")

    pending, orphan_ids = _activation_reconciliation(
        [edeka, aldi],
        [linked_store, orphan_store],
    )

    assert len(pending) == 1
    assert pending[0]["candidate"].retailer == "ALDI SÜD"
    assert pending[0]["promotion_candidate"].id == 22
    assert pending[0]["address_verified"] is True
    assert pending[0]["coordinates_verified"] is True
    assert pending[0]["official_source_verified"] is True
    assert orphan_ids == {999}


def test_activation_reconciliation_does_not_mark_linked_store_as_orphan():
    candidate = _candidate(
        30,
        "rewe-linked",
        "REWE",
        "Am Schwimmbad 1",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="promoted",
        matched_store_id=300,
    )
    store = _store(300, "REWE", "Am Schwimmbad 1")

    pending, orphan_ids = _activation_reconciliation([candidate], [store])

    assert pending == []
    assert orphan_ids == set()
