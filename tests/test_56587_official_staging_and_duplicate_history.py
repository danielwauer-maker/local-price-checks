from __future__ import annotations

from urllib.parse import unquote

import pytest
from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
import app.admin_coverage_routes as coverage_routes
from app.coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.models import CollectionRun, Store
from app.postcode_coverage_service import promote_candidate_to_store
from app.retailer_store_sources import (
    CuratedOfficialAdapter,
    RetailerSourceResult,
    RetailerStoreRecord,
    default_retailer_adapters,
    stage_official_store_candidates,
)


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _store(
    store_id: int,
    retailer: str,
    name: str,
    address: str,
    city: str,
    latitude: float,
    longitude: float,
    external_id: str | None = None,
) -> Store:
    return Store(
        id=store_id,
        retailer=retailer,
        name=name,
        postal_code="56587",
        city=city,
        address=address,
        latitude=latitude,
        longitude=longitude,
        active=False,
        benchmark_verified=False,
        external_id=external_id,
    )


def _rewe_store(store_id: int, name: str) -> Store:
    return _store(
        store_id,
        "REWE",
        name,
        "Kirschbüchel 2",
        "Straßenhaus",
        50.5407,
        7.5187,
        "1940425",
    )


def _ready_rewe_candidate() -> StoreDiscoveryCandidate:
    return StoreDiscoveryCandidate(
        discovery_key="official-rewe-56587",
        postal_code="56587",
        retailer="REWE",
        name="REWE Dennis Weirich",
        address="Kirschbüchel 2",
        city="Straßenhaus",
        latitude=50.5407,
        longitude=7.5187,
        source="official:rewe",
        source_external_id="1940425",
        source_url=(
            "https://www.rewe.de/marktseite/strassenhaus/1940425/"
            "rewe-markt-kirschbuechel-2/"
        ),
        status="verified",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
    )


def _aldi_adapter():
    return next(
        adapter for adapter in default_retailer_adapters()
        if adapter.retailer == "ALDI SÜD"
    )


def test_56587_rewe_stages_even_when_aldi_coordinate_evidence_conflicts():
    db = _db()
    db.add_all([
        _rewe_store(2, "REWE Straßenhaus"),
        _rewe_store(15, "REWE Dennis Weirich"),
        _store(
            6,
            "ALDI SÜD",
            "ALDI SÜD Oberhonnefeld-Gierend",
            "Über dem Stellweg 5",
            "Oberhonnefeld-Gierend",
            50.555,
            7.52,
        ),
        StoreDiscoveryCandidate(
            discovery_key="aldi-osm-conflict",
            postal_code="56587",
            retailer="ALDI SÜD",
            name="ALDI Süd",
            address="Über dem Stellweg 5",
            city="Oberhonnefeld-Gierend",
            latitude=50.5587564,
            longitude=7.5275799,
            source="osm",
            source_external_id="way/49996568",
            status="discovered",
        ),
    ])
    db.commit()

    created, updated, results = stage_official_store_candidates(db, "56587")

    assert (created, updated) == (1, 0)
    rewe = db.query(StoreDiscoveryCandidate).filter_by(
        source="official:rewe", source_external_id="1940425"
    ).one()
    assert rewe.address == "Kirschbüchel 2"
    assert rewe.official_source_verified is True
    assert db.query(StoreDiscoveryCandidate).filter_by(source="official:aldi_sued").count() == 0
    statuses = {result.retailer: result.status for result in results}
    assert statuses["REWE"] == "manual_verification_required"
    assert statuses["ALDI SÜD"] == "partial_failure"


def test_aldi_coordinate_conflict_stays_fail_closed_and_is_not_counted_as_created():
    db = _db()
    db.add_all([
        _store(
            6,
            "ALDI SÜD",
            "ALDI SÜD Oberhonnefeld-Gierend",
            "Über dem Stellweg 5",
            "Oberhonnefeld-Gierend",
            50.555,
            7.52,
        ),
        StoreDiscoveryCandidate(
            discovery_key="aldi-osm-conflict",
            postal_code="56587",
            retailer="ALDI SÜD",
            name="ALDI Süd",
            address="Über dem Stellweg 5",
            city="Oberhonnefeld-Gierend",
            latitude=50.5587564,
            longitude=7.5275799,
            source="osm",
            source_external_id="way/49996568",
            status="discovered",
        ),
    ])
    db.commit()

    created, updated, results = stage_official_store_candidates(
        db, "56587", adapters=(_aldi_adapter(),)
    )

    assert (created, updated) == (0, 0)
    assert db.query(StoreDiscoveryCandidate).filter_by(source="official:aldi_sued").count() == 0
    assert results[0].status == "partial_failure"
    assert "no unique reviewed coordinate evidence" in results[0].note


def test_aldi_official_candidate_stages_when_coordinate_evidence_is_unique():
    db = _db()
    db.add(_store(
        6,
        "ALDI SÜD",
        "ALDI SÜD Oberhonnefeld-Gierend",
        "Über dem Stellweg 5",
        "Oberhonnefeld-Gierend",
        50.555,
        7.52,
    ))
    db.commit()

    created, updated, results = stage_official_store_candidates(
        db, "56587", adapters=(_aldi_adapter(),)
    )

    assert (created, updated) == (1, 0)
    candidate = db.query(StoreDiscoveryCandidate).filter_by(source="official:aldi_sued").one()
    assert (candidate.latitude, candidate.longitude) == (50.555, 7.52)
    assert candidate.official_source_verified is True
    assert results[0].status == "manual_verification_required"


def test_rewe_official_staging_is_idempotent_with_duplicate_legacy_stores():
    db = _db()
    db.add_all([
        _rewe_store(2, "REWE Straßenhaus"),
        _rewe_store(15, "REWE Dennis Weirich"),
    ])
    db.commit()

    first = stage_official_store_candidates(db, "56587")
    second = stage_official_store_candidates(db, "56587")

    assert first[:2] == (1, 0)
    assert second[:2] == (0, 1)
    assert db.query(StoreDiscoveryCandidate).filter_by(
        source="official:rewe", source_external_id="1940425"
    ).count() == 1


def test_promotion_reuses_unique_history_bearing_rewe_store_and_preserves_empty_duplicate():
    db = _db()
    canonical = _rewe_store(2, "REWE Straßenhaus")
    duplicate = _rewe_store(15, "REWE Dennis Weirich")
    candidate = _ready_rewe_candidate()
    db.add_all([canonical, duplicate, candidate])
    db.flush()
    run = CollectionRun(store_id=2, source_key="rewe", status="success")
    db.add(run)
    db.commit()
    duplicate_before = (
        duplicate.name,
        duplicate.address,
        duplicate.external_id,
        duplicate.active,
        duplicate.benchmark_verified,
    )

    store = promote_candidate_to_store(db, candidate.id)

    assert store.id == 2
    assert db.get(StoreDiscoveryCandidate, candidate.id).matched_store_id == 2
    assert db.query(CollectionRun).filter_by(store_id=2).count() == 1
    assert db.query(CollectionRun).filter_by(store_id=15).count() == 0
    duplicate_after = db.get(Store, 15)
    assert (
        duplicate_after.name,
        duplicate_after.address,
        duplicate_after.external_id,
        duplicate_after.active,
        duplicate_after.benchmark_verified,
    ) == duplicate_before
    assert db.get(Store, 2).active is False
    assert db.get(Store, 2).benchmark_verified is False


def test_promotion_fails_closed_when_both_matching_stores_have_history():
    db = _db()
    candidate = _ready_rewe_candidate()
    db.add_all([
        _rewe_store(2, "REWE Straßenhaus"),
        _rewe_store(15, "REWE Dennis Weirich"),
        candidate,
    ])
    db.flush()
    db.add_all([
        CollectionRun(store_id=2, source_key="rewe", status="success"),
        CollectionRun(store_id=15, source_key="rewe", status="success"),
    ])
    db.commit()

    with pytest.raises(ValueError, match="Historienlage ist nicht eindeutig"):
        promote_candidate_to_store(db, candidate.id)

    db.rollback()
    assert db.get(StoreDiscoveryCandidate, candidate.id).matched_store_id is None


def test_promotion_fails_closed_when_duplicate_matches_have_no_history():
    db = _db()
    candidate = _ready_rewe_candidate()
    db.add_all([
        _rewe_store(2, "REWE Straßenhaus"),
        _rewe_store(15, "REWE Dennis Weirich"),
        candidate,
    ])
    db.commit()

    with pytest.raises(ValueError, match="Historienlage ist nicht eindeutig"):
        promote_candidate_to_store(db, candidate.id)

    db.rollback()
    assert db.get(StoreDiscoveryCandidate, candidate.id).matched_store_id is None


def test_admin_discovery_runs_official_staging_even_when_osm_fails(monkeypatch):
    db = _db()
    db.add(CoveragePostalCode(postal_code="56587", city="Straßenhaus", enabled=True))
    db.commit()
    official_calls: list[str] = []

    def fail_osm(_db, postal_code):
        raise RuntimeError("overpass unavailable")

    def stage_official(_db, postal_code):
        official_calls.append(postal_code)
        return 1, 0, (
            RetailerSourceResult(
                retailer="REWE",
                status="manual_verification_required",
                source_type="fixture",
                source_url="https://example.invalid/rewe",
            ),
        )

    monkeypatch.setattr(coverage_routes, "stage_postcode_candidates", fail_osm)
    monkeypatch.setattr(coverage_routes, "stage_official_store_candidates", stage_official)

    response = coverage_routes.discover_postcode("56587", db=db, actor="admin")
    location = unquote(response.headers["location"])

    assert official_calls == ["56587"]
    assert "osm-failed=RuntimeError" in location
    assert "official-new=1" in location
    assert "official-updated=0" in location


def test_admin_discovery_surfaces_partial_and_unavailable_official_sources(monkeypatch):
    db = _db()
    db.add(CoveragePostalCode(postal_code="56587", city="Straßenhaus", enabled=True))
    db.commit()

    monkeypatch.setattr(coverage_routes, "stage_postcode_candidates", lambda _db, _pc: (4, 0))
    monkeypatch.setattr(
        coverage_routes,
        "stage_official_store_candidates",
        lambda _db, _pc: (
            1,
            0,
            (
                RetailerSourceResult(
                    retailer="ALDI SÜD",
                    status="partial_failure",
                    source_type="fixture",
                    source_url="https://example.invalid/aldi",
                ),
                RetailerSourceResult(
                    retailer="EDEKA",
                    status="source_unavailable",
                    source_type="fixture",
                    source_url="https://example.invalid/edeka",
                ),
            ),
        ),
    )

    response = coverage_routes.discover_postcode("56587", db=db, actor="admin")
    location = unquote(response.headers["location"])

    assert "osm-new=4" in location
    assert "official-new=1" in location
    assert "official-partial=ALDI SÜD" in location
    assert "official-unavailable=EDEKA" in location


def test_failed_record_flush_does_not_increment_official_created_count(monkeypatch):
    db = _db()
    adapter = CuratedOfficialAdapter(
        key="fixture_rewe",
        retailer="REWE",
        directory_url="https://example.invalid/rewe",
        records=(RetailerStoreRecord(
            retailer="REWE",
            name="REWE Fixture",
            address="Teststraße 1",
            postal_code="56587",
            city="Straßenhaus",
            latitude=50.54,
            longitude=7.51,
            external_id="fixture-1",
            source_url="https://example.invalid/rewe/fixture-1",
            source_identifier="fixture-rewe-1",
        ),),
    )
    original_flush = db.flush
    flush_calls = 0

    def flaky_flush(*args, **kwargs):
        nonlocal flush_calls
        flush_calls += 1
        if flush_calls == 2:
            raise RuntimeError("fixture flush failure")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", flaky_flush)

    created, updated, results = stage_official_store_candidates(
        db, "56587", adapters=(adapter,)
    )

    assert (created, updated) == (0, 0)
    assert db.query(StoreDiscoveryCandidate).count() == 0
    assert results[0].status == "partial_failure"
    assert "fixture flush failure" in results[0].note
