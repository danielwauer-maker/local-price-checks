from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app import admin_coverage_routes
from app.coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.models import Store
from app.retailer_store_sources import stage_official_store_candidates


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _aldi_candidate(*, source_url: str) -> StoreDiscoveryCandidate:
    return StoreDiscoveryCandidate(
        discovery_key="aldi-osm-56587",
        postal_code="56587",
        retailer="ALDI SÜD",
        name="ALDI Süd",
        address="Über dem Stellweg 5",
        city="Oberhonnefeld-Gierend",
        latitude=50.5587564,
        longitude=7.5275799,
        source="osm",
        source_external_id="way/49996568",
        source_url=source_url,
    )


def _stale_aldi_store() -> Store:
    return Store(
        retailer="ALDI SÜD",
        name="ALDI SÜD Oberhonnefeld-Gierend",
        postal_code="56587",
        city="Oberhonnefeld-Gierend",
        address="Über dem Stellweg 5",
        latitude=50.555,
        longitude=7.52,
        active=False,
        benchmark_verified=False,
    )


def test_direct_aldi_branch_page_resolves_conflicting_legacy_seed_pin():
    db = _db()
    db.add(_stale_aldi_store())
    db.add(_aldi_candidate(
        source_url=(
            "https://filialen.aldi-sued.de/rheinland-pfalz/"
            "oberhonnefeld-gierend/ueber-dem-stellweg-5"
        )
    ))
    db.commit()

    created, updated, results = stage_official_store_candidates(db, "56587")

    assert created == 2  # reviewed REWE + ALDI official candidates
    assert updated == 0
    aldi_result = next(result for result in results if result.retailer == "ALDI SÜD")
    assert aldi_result.status != "partial_failure"

    official_aldi = db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.postal_code == "56587",
        StoreDiscoveryCandidate.retailer == "ALDI SÜD",
        StoreDiscoveryCandidate.source.like("official:%"),
    ).one()
    assert official_aldi.latitude == 50.5587564
    assert official_aldi.longitude == 7.5275799
    assert official_aldi.official_source_verified is True

    official_rewe = db.query(StoreDiscoveryCandidate).filter_by(
        postal_code="56587",
        retailer="REWE",
        source_external_id="1940425",
    ).one()
    assert official_rewe.address == "Kirschbüchel 2"
    db.close()


def test_conflicting_aldi_pins_without_direct_official_page_still_fail_closed():
    db = _db()
    db.add(_stale_aldi_store())
    db.add(_aldi_candidate(source_url="https://www.openstreetmap.org/way/49996568"))
    db.commit()

    created, updated, results = stage_official_store_candidates(db, "56587")

    # REWE has a reviewed curated pin and can still stage independently.
    assert created == 1
    assert updated == 0
    aldi_result = next(result for result in results if result.retailer == "ALDI SÜD")
    assert aldi_result.status == "partial_failure"
    assert "no unique reviewed coordinate evidence" in aldi_result.note
    assert db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.postal_code == "56587",
        StoreDiscoveryCandidate.retailer == "ALDI SÜD",
        StoreDiscoveryCandidate.source.like("official:%"),
    ).count() == 0
    db.close()


def test_postcode_reconcile_runs_official_staging_even_when_osm_refresh_fails(monkeypatch):
    db = _db()
    db.add(CoveragePostalCode(postal_code="56587", city="Straßenhaus", enabled=True))
    db.commit()

    calls = {"official": 0}

    def broken_osm(_db, _postal_code):
        raise RuntimeError("OSM unavailable")

    def successful_official(_db, _postal_code):
        calls["official"] += 1
        return 1, 0, (
            SimpleNamespace(status="manual_verification_required"),
            SimpleNamespace(status="partial_failure"),
        )

    monkeypatch.setattr(admin_coverage_routes, "stage_postcode_candidates", broken_osm)
    monkeypatch.setattr(admin_coverage_routes, "stage_official_store_candidates", successful_official)

    response = admin_coverage_routes.discover_postcode("56587", db=db, actor="test")

    assert calls["official"] == 1
    location = response.headers["location"]
    assert "osm-failed=RuntimeError" in location
    assert "official-new=1" in location
    assert "official-partial=1" in location
    db.close()
