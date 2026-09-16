from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
import app.admin_coverage_routes as coverage_routes
from app.coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.models import Store
from app.retailer_store_sources import (
    CURATED_OFFICIAL_STORES,
    RetailerSourceResult,
    _official_candidate_key,
    _safe_staging_error,
    default_retailer_adapters,
    stage_official_store_candidates,
)


ALDI_56587_URL = (
    "https://filialen.aldi-sued.de/rheinland-pfalz/oberhonnefeld-gierend/"
    "ueber-dem-stellweg-5"
)


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _aldi_discovery_candidate(*, source_url: str = ALDI_56587_URL, **overrides):
    values = {
        "discovery_key": "aldi-osm-56587",
        "postal_code": "56587",
        "retailer": "ALDI SÜD",
        "name": "ALDI Süd",
        "address": "Über dem Stellweg 5",
        "city": "Oberhonnefeld-Gierend",
        "latitude": 50.5587564,
        "longitude": 7.5275799,
        "source": "osm",
        "source_external_id": "way/49996568",
        "source_url": source_url,
    }
    values.update(overrides)
    return StoreDiscoveryCandidate(**values)


def _official_rewe_56587():
    adapter = next(row for row in default_retailer_adapters() if row.retailer == "REWE")
    record = next(
        row for row in CURATED_OFFICIAL_STORES
        if row.retailer == "REWE" and row.postal_code == "56587"
    )
    return adapter, record


def test_rewe_56587_stages_despite_duplicate_legacy_stores_and_rejected_candidate_stays_rejected():
    db = _db()
    store2 = Store(
        id=2,
        retailer="REWE",
        name="REWE Straßenhaus",
        address="Kirschbüchel 2",
        postal_code="56587",
        city="Straßenhaus",
        latitude=50.5407,
        longitude=7.5187,
        external_id="1940425",
        active=False,
        benchmark_verified=False,
    )
    store15 = Store(
        id=15,
        retailer="REWE",
        name="REWE Dennis Weirich Legacy",
        address="Kirschbüchel 2",
        postal_code="56587",
        city="Straßenhaus",
        latitude=50.5407,
        longitude=7.5187,
        external_id="1940425",
        active=False,
        benchmark_verified=False,
    )
    rejected = StoreDiscoveryCandidate(
        id=23,
        discovery_key="rewe-raiffeisenstrasse-rejected",
        postal_code="56587",
        retailer="REWE",
        name="REWE",
        address="Raiffeisenstraße",
        city="Straßenhaus",
        latitude=50.541,
        longitude=7.519,
        source="osm",
        source_external_id="way/92219239",
        status="rejected",
    )
    db.add_all([store2, store15, rejected, _aldi_discovery_candidate()])
    db.commit()
    before = {
        store.id: (store.name, store.active, store.benchmark_verified, store.external_id)
        for store in (store2, store15)
    }

    created, _, _ = stage_official_store_candidates(db, "56587")

    official = db.query(StoreDiscoveryCandidate).filter_by(
        postal_code="56587",
        retailer="REWE",
        source_external_id="1940425",
    ).one()
    assert official.source == "official:rewe"
    assert official.address == "Kirschbüchel 2"
    assert official.latitude == 50.5407
    assert official.longitude == 7.5187
    assert created == 2
    assert db.get(StoreDiscoveryCandidate, 23).status == "rejected"
    assert {
        store.id: (store.name, store.active, store.benchmark_verified, store.external_id)
        for store in (db.get(Store, 2), db.get(Store, 15))
    } == before
    db.close()


def test_aldi_source_confirmed_current_candidate_outranks_unverified_legacy_store_pin():
    db = _db()
    legacy = Store(
        id=6,
        retailer="ALDI SÜD",
        name="ALDI SÜD Oberhonnefeld-Gierend Legacy",
        address="Über dem Stellweg 5",
        postal_code="56587",
        city="Oberhonnefeld-Gierend",
        latitude=50.555,
        longitude=7.52,
        active=False,
        benchmark_verified=False,
    )
    current = _aldi_discovery_candidate()
    db.add_all([legacy, current])
    db.commit()

    created, _, results = stage_official_store_candidates(db, "56587")

    official = db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.postal_code == "56587",
        StoreDiscoveryCandidate.retailer == "ALDI SÜD",
        StoreDiscoveryCandidate.source.like("official:%"),
    ).one()
    assert created == 2
    assert official.latitude == current.latitude
    assert official.longitude == current.longitude
    assert official.source_url == ALDI_56587_URL
    assert (legacy.latitude, legacy.longitude) == (50.555, 7.52)
    aldi_result = next(row for row in results if row.retailer == "ALDI SÜD")
    assert aldi_result.status != "partial_failure"
    db.close()


def test_unresolved_aldi_pin_conflict_remains_fail_closed_without_blocking_rewe_or_inflating_count():
    db = _db()
    db.add_all([
        Store(
            id=6,
            retailer="ALDI SÜD",
            name="ALDI SÜD Oberhonnefeld-Gierend Legacy",
            address="Über dem Stellweg 5",
            postal_code="56587",
            city="Oberhonnefeld-Gierend",
            latitude=50.555,
            longitude=7.52,
            active=False,
            benchmark_verified=False,
        ),
        _aldi_discovery_candidate(source_url="https://www.openstreetmap.org/way/49996568"),
    ])
    db.commit()

    created, _, results = stage_official_store_candidates(db, "56587")

    assert created == 1
    assert db.query(StoreDiscoveryCandidate).filter_by(
        postal_code="56587",
        retailer="REWE",
        source_external_id="1940425",
    ).one_or_none() is not None
    assert db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.postal_code == "56587",
        StoreDiscoveryCandidate.retailer == "ALDI SÜD",
        StoreDiscoveryCandidate.source.like("official:%"),
    ).one_or_none() is None
    aldi_result = next(row for row in results if row.retailer == "ALDI SÜD")
    assert aldi_result.status == "partial_failure"
    assert "ALDI SÜD Oberhonnefeld-Gierend" in aldi_result.note
    assert "aldi-sued-56587-ueber-dem-stellweg-5" in aldi_result.note
    assert "no unique reviewed coordinate evidence" in aldi_result.note
    db.close()


def test_source_refresh_preserves_verified_promoted_identity_gates():
    db = _db()
    adapter, record = _official_rewe_56587()
    key = _official_candidate_key(adapter.key, record)
    existing = StoreDiscoveryCandidate(
        discovery_key=key,
        postal_code=record.postal_code,
        retailer=record.retailer,
        name=record.name,
        address=record.address,
        city=record.city,
        latitude=record.latitude,
        longitude=record.longitude,
        source="official:rewe",
        source_external_id=record.external_id,
        source_url="https://example.invalid/old-source",
        status="promoted",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        verification_note="bestehende geprüfte Identität",
    )
    db.add_all([existing, _aldi_discovery_candidate()])
    db.commit()

    _, updated, _ = stage_official_store_candidates(db, "56587")
    db.refresh(existing)

    assert updated == 1
    assert existing.status == "promoted"
    assert existing.address_verified is True
    assert existing.coordinates_verified is True
    assert existing.official_source_verified is True
    assert existing.source_url == record.source_url
    db.close()


def test_official_staging_does_not_mutate_existing_public_store():
    db = _db()
    public = Store(
        id=2,
        retailer="REWE",
        name="REWE Straßenhaus Public",
        address="Kirschbüchel 2",
        postal_code="56587",
        city="Straßenhaus",
        latitude=50.5407,
        longitude=7.5187,
        external_id="1940425",
        source_url="https://legacy.example.invalid/rewe",
        active=True,
        benchmark_verified=True,
    )
    db.add_all([public, _aldi_discovery_candidate()])
    db.commit()
    before = (
        public.name,
        public.address,
        public.latitude,
        public.longitude,
        public.external_id,
        public.source_url,
        public.active,
        public.benchmark_verified,
    )

    stage_official_store_candidates(db, "56587")
    db.refresh(public)

    assert (
        public.name,
        public.address,
        public.latitude,
        public.longitude,
        public.external_id,
        public.source_url,
        public.active,
        public.benchmark_verified,
    ) == before
    db.close()


def test_admin_discovery_redirect_surfaces_partial_failure_details(monkeypatch):
    db = _db()
    db.add(CoveragePostalCode(postal_code="56587", city="Straßenhaus", enabled=True))
    db.commit()
    monkeypatch.setattr(coverage_routes, "stage_postcode_candidates", lambda _db, _pc: (0, 0))
    failure = RetailerSourceResult(
        retailer="ALDI SÜD",
        status="partial_failure",
        source_type="official_retailer_directory",
        source_url="https://www.aldi-sued.de/filialen.html",
        note=(
            "Staging-Fehler: ALDI SÜD Oberhonnefeld-Gierend "
            "[aldi-sued-56587-ueber-dem-stellweg-5]: RuntimeError: pin conflict"
        ),
    )
    monkeypatch.setattr(
        coverage_routes,
        "stage_official_store_candidates",
        lambda _db, _pc: (0, 0, (failure,)),
    )

    response = coverage_routes.discover_postcode("56587", db=db, actor="test-admin")
    result = parse_qs(urlsplit(response.headers["location"]).query)["result"][0]

    assert "QUELLENFEHLER=" in result
    assert "ALDI SÜD" in result
    assert "ALDI SÜD Oberhonnefeld-Gierend" in result
    assert "aldi-sued-56587-ueber-dem-stellweg-5" in result
    assert "RuntimeError: pin conflict" in result
    db.close()


def test_integrity_error_diagnostic_does_not_leak_sql_or_parameters():
    error = IntegrityError(
        "INSERT INTO store_discovery_candidates(secret) VALUES (?)",
        {"secret": "do-not-leak"},
        Exception("constraint failed"),
    )

    message = _safe_staging_error(error)

    assert message == "IntegrityError: Datenbank-Constraint verletzt"
    assert "do-not-leak" not in message
    assert "INSERT" not in message
