from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.admin_routes import _admin
from app.admin_coverage_routes import safe_external_url
from app.api_main import app
from app.coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from app.db import Base, create_database_engine, get_db
from app.models import Store
from app.postcode_coverage_service import (
    addresses_match,
    candidate_ready_for_promotion,
    seed_initial_postcode_coverage,
    stage_postcode_candidates,
    verify_candidate_address_coordinates,
)
from app.postcode_geometry import (
    PostcodeGeometry,
    import_postcode_geometry,
    load_bundled_postcode_geometries,
    postcode_feature,
)
from app.postcode_reconciliation import reconcile_postcode_coverage
from app.retailer_store_sources import (
    RetailerSourceResult,
    RetailerStoreRecord,
    SUPPORTED_RETAILERS,
    default_retailer_adapters,
    stage_official_store_candidates,
)


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _candidate(key: str, *, source: str = "osm", **overrides):
    values = {
        "discovery_key": key,
        "postal_code": "56305",
        "retailer": "Lidl",
        "name": "Lidl Puderbach",
        "address": "Urbacher Straße 31a",
        "city": "Puderbach",
        "latitude": 50.592267,
        "longitude": 7.608759,
        "source": source,
    }
    values.update(overrides)
    return StoreDiscoveryCandidate(**values)


def _source(status: str = "supported") -> tuple[RetailerSourceResult, ...]:
    return (RetailerSourceResult("Lidl", status, "fixture", "https://example.invalid"),)


def test_initial_postcodes_receive_bundled_polygon_geometry_and_centers():
    db = _db()
    seed_initial_postcode_coverage(db)
    rows = db.query(CoveragePostalCode).all()
    assert len(rows) == 8
    assert all(row.geometry_geojson and row.geometry_source for row in rows)
    assert all(json.loads(row.geometry_geojson)["type"] in {"Polygon", "MultiPolygon"} for row in rows)
    assert all(row.center_lat is not None and row.center_lng is not None for row in rows)
    assert {row.postal_code for row in rows} == set(load_bundled_postcode_geometries())
    db.close()


def test_polygon_import_uses_existing_fields_and_provider_failure_keeps_cache():
    db = _db()
    first = PostcodeGeometry(
        "12345", "Testort", 50.0, 7.0, "fixture:v1",
        {"type": "Polygon", "coordinates": [[[7.0, 50.0], [7.1, 50.0], [7.1, 50.1], [7.0, 50.0]]]},
    )
    row = import_postcode_geometry(db, "12345", provider=lambda _: first, enabled=False)
    before = (row.geometry_source, row.geometry_geojson, row.center_lat, row.center_lng)

    def unavailable(_):
        raise RuntimeError("network unavailable")

    with pytest.raises(RuntimeError):
        import_postcode_geometry(db, "12345", provider=unavailable)
    db.refresh(row)
    assert (row.geometry_source, row.geometry_geojson, row.center_lat, row.center_lng) == before
    assert row.enabled is False
    db.close()


def test_feature_payload_uses_same_postcode_row_as_list_and_map():
    db = _db()
    seed_initial_postcode_coverage(db)
    row = db.query(CoveragePostalCode).filter_by(postal_code="56305").one()
    feature = postcode_feature(row, {"status": "verification_pending", "expected": 2})
    assert feature["properties"]["postal_code"] == row.postal_code
    assert feature["properties"]["enabled"] == row.enabled
    assert feature["properties"]["expected"] == 2
    db.close()


def test_neighbour_postcode_from_provider_is_never_staged(monkeypatch):
    db = _db()
    monkeypatch.setattr(
        "app.postcode_coverage_service.discover_postcode_supermarkets",
        lambda _: [{
            "discovery_key": "wrong-postcode",
            "postal_code": "56316",
            "retailer": "Lidl",
            "name": "Lidl Nachbarort",
            "address": "Nachbarweg 1",
            "city": "Raubach",
            "latitude": 50.57,
            "longitude": 7.62,
            "source": "osm",
            "source_external_id": "node/9",
            "source_url": None,
        }],
    )
    assert stage_postcode_candidates(db, "56305") == (0, 0)
    assert db.query(StoreDiscoveryCandidate).count() == 0
    db.close()


def test_six_retailer_adapters_are_central_and_honest_about_completeness():
    adapters = default_retailer_adapters()
    assert {adapter.retailer for adapter in adapters} == set(SUPPORTED_RETAILERS)
    results = [adapter.stores_for_postcode("56305") for adapter in adapters]
    assert all(result.status == "manual_verification_required" for result in results)
    assert {store.retailer for result in results for store in result.stores} == {"Lidl", "EDEKA"}


def test_official_adapter_records_are_staged_but_never_promoted_automatically():
    db = _db()
    created, updated, _ = stage_official_store_candidates(db, "56305")
    rows = db.query(StoreDiscoveryCandidate).all()
    assert (created, updated) == (2, 0)
    assert len(rows) == 2
    assert all(row.source.startswith("official:") and row.official_source_verified for row in rows)
    assert all(not row.address_verified and not row.coordinates_verified for row in rows)
    assert all(not candidate_ready_for_promotion(row) for row in rows)
    assert db.query(Store).count() == 0
    db.close()


def test_missing_official_source_blocks_promotion_even_after_address_and_position_checks():
    candidate = _candidate(
        "candidate",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=False,
    )
    assert candidate_ready_for_promotion(candidate) is False


def test_reconciliation_detects_missing_expected_store():
    db = _db()
    postcode = CoveragePostalCode(postal_code="56305", enabled=True)
    db.add_all([postcode, _candidate("expected", source="official:lidl", official_source_verified=True)])
    db.commit()
    summary = reconcile_postcode_coverage(db, postcode, source_results=_source())
    assert summary.expected == 1
    assert summary.found == 0
    assert summary.missing_expected == 1
    assert summary.status == "incomplete"
    db.close()


def test_reconciliation_detects_additional_osm_candidate():
    db = _db()
    postcode = CoveragePostalCode(postal_code="56305", enabled=True)
    expected = _candidate("expected", source="official:lidl", official_source_verified=True)
    matched = _candidate("matched")
    extra = _candidate(
        "extra", retailer="EDEKA", name="EDEKA Extra", address="Marktweg 2",
        latitude=50.60, longitude=7.61,
    )
    db.add_all([postcode, expected, matched, extra])
    db.commit()
    summary = reconcile_postcode_coverage(db, postcode, source_results=_source())
    assert summary.expected == 1
    assert summary.found == 2
    assert summary.missing_expected == 0
    assert summary.additional_discovered == 1
    assert summary.status == "verification_pending"
    db.close()


def test_reconciliation_can_be_complete_only_with_all_gates_and_promotion():
    db = _db()
    postcode = CoveragePostalCode(postal_code="56305", enabled=True)
    expected = _candidate("expected", source="official:lidl", official_source_verified=True)
    discovered = _candidate(
        "matched", address_verified=True, coordinates_verified=True,
        official_source_verified=True, status="promoted",
    )
    store = Store(
        retailer="Lidl", name="Lidl Complete", postal_code="56305", city="Puderbach",
        address="Urbacher Straße 31a", latitude=50.592267, longitude=7.608759,
        active=True, benchmark_verified=False,
    )
    db.add_all([postcode, expected, discovered, store])
    db.flush()
    discovered.matched_store_id = store.id
    db.commit()
    summary = reconcile_postcode_coverage(db, postcode, source_results=_source())
    assert summary.status == "complete"
    assert summary.promoted == 1
    assert store.benchmark_verified is False
    db.close()


def test_unrelated_existing_store_does_not_satisfy_promotion_requirement():
    db = _db()
    postcode = CoveragePostalCode(postal_code="56305", enabled=True)
    expected = _candidate("expected", source="official:lidl", official_source_verified=True)
    unrelated = Store(
        retailer="EDEKA", name="EDEKA Puderbach", postal_code="56305", city="Puderbach",
        address="Mittelstraße 2", latitude=50.60, longitude=7.61, active=True,
    )
    db.add_all([postcode, expected, unrelated])
    db.commit()
    summary = reconcile_postcode_coverage(db, postcode, source_results=_source())
    assert summary.promoted == 0
    assert summary.status != "complete"
    db.close()


def test_identity_matching_counts_preexisting_store_with_normalized_address():
    db = _db()
    postcode = CoveragePostalCode(postal_code="56305", enabled=True)
    expected = _candidate("expected", source="official:lidl", official_source_verified=True)
    existing = Store(
        retailer="Lidl", name="Lidl Puderbach", postal_code="56305", city="Puderbach",
        address="Urbacherstr. 31a", latitude=50.592267, longitude=7.608759, active=True,
    )
    db.add_all([postcode, expected, existing])
    db.commit()
    summary = reconcile_postcode_coverage(db, postcode, source_results=_source())
    assert summary.promoted == 1
    db.close()


def test_identity_matching_prefers_matching_external_store_id():
    db = _db()
    postcode = CoveragePostalCode(postal_code="56305", enabled=True)
    expected = _candidate(
        "expected", source="official:lidl", source_external_id="lidl-56305",
        official_source_verified=True,
    )
    existing = Store(
        retailer="Lidl", name="Lidl Puderbach", postal_code="56305", city="Puderbach",
        address="Historische Adresse 1", latitude=50.592267, longitude=7.608759,
        external_id="lidl-56305", active=True,
    )
    db.add_all([postcode, expected, existing])
    db.commit()
    assert reconcile_postcode_coverage(db, postcode, source_results=_source()).promoted == 1
    db.close()


@pytest.mark.parametrize(
    ("enabled", "source_status", "expected_status"),
    ((False, "supported", "disabled"), (True, "source_unavailable", "source_unavailable"), (True, "supported", "no_expected_stores")),
)
def test_reconciliation_statuses_do_not_claim_false_completeness(enabled, source_status, expected_status):
    db = _db()
    postcode = CoveragePostalCode(postal_code="12345", enabled=enabled)
    db.add(postcode)
    db.commit()
    assert reconcile_postcode_coverage(db, postcode, source_results=_source(source_status)).status == expected_status
    db.close()


def test_verification_rejects_address_postcode_and_retailer_mismatch():
    candidate = _candidate("candidate")
    for reference in (
        _candidate("address", source="official:lidl", address="Andere Straße 9"),
        _candidate("postcode", source="official:lidl", postal_code="56316"),
        _candidate("retailer", source="official:lidl", retailer="REWE"),
    ):
        address_ok, coordinates_ok, note = verify_candidate_address_coordinates(candidate, reference)
        assert address_ok is False
        assert coordinates_ok is False
        assert "abweichend" in note


def test_verification_rejects_coordinate_distance_above_threshold():
    candidate = _candidate("candidate")
    reference = _candidate(
        "official", source="official:lidl", latitude=50.602267, longitude=7.608759,
    )
    address_ok, coordinates_ok, note = verify_candidate_address_coordinates(candidate, reference)
    assert address_ok is True
    assert coordinates_ok is False
    assert "über 250 m" in note


def test_address_matching_normalizes_common_street_abbreviations():
    assert addresses_match("Urbacher Straße 31a", "Urbacherstr. 31a")


@pytest.mark.parametrize(
    "value",
    (
        None, "", "javascript:alert(1)", "data:text/html,x", "file:///tmp/x",
        "/relative", "example.com", "https:///missing-host", "https://exa mple.com",
        "https://example.com:not-a-port",
    ),
)
def test_safe_external_url_rejects_non_http_and_malformed_values(value):
    assert safe_external_url(value) is None


@pytest.mark.parametrize("value", ("https://example.com/store", "http://example.com/store"))
def test_safe_external_url_accepts_absolute_http_urls(value):
    assert safe_external_url(value) == value


def test_admin_map_and_toggle_endpoint_share_the_seeded_postcode_state(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'admin-map.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    seed_initial_postcode_coverage(db)
    db.add_all([
        _candidate("unsafe-url", source_url="javascript:alert(1)"),
        _candidate("safe-url", source_url="https://example.com/store"),
    ])
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[_admin] = lambda: "test-admin"
    client = TestClient(app)
    try:
        response = client.get("/admin/coverage")
        assert response.status_code == 200
        assert "coverage-map" in response.text
        assert "56305" in response.text
        assert "OpenStreetMap contributors" in response.text
        assert 'href="javascript:alert(1)"' not in response.text
        assert 'href="https://example.com/store"' in response.text
        toggled = client.post(
            "/admin/coverage/postcodes/56305/toggle",
            data={"enabled": "0"},
            follow_redirects=False,
        )
        assert toggled.status_code == 303
        assert db.query(CoveragePostalCode).filter_by(postal_code="56305").one().enabled is False
    finally:
        app.dependency_overrides.clear()
        db.close()
