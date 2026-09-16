from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.models import Store
from app.postcode_coverage_service import stage_postcode_candidates
from app.retailer_store_sources import (
    CURATED_OFFICIAL_STORES,
    CuratedOfficialAdapter,
    RetailerStoreRecord,
    stage_official_store_candidates,
)


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _lidl_record(*, latitude: float, longitude: float, source_url: str = "https://example.invalid/lidl"):
    return RetailerStoreRecord(
        retailer="Lidl",
        name="Lidl Puderbach",
        address="Urbacherstraße L264",
        postal_code="56305",
        city="Puderbach",
        latitude=latitude,
        longitude=longitude,
        external_id="lidl-puderbach-urbacherstr-l264",
        source_url=source_url,
        source_identifier="lidl-puderbach-urbacherstr-l264",
    )


def _lidl_adapter(record: RetailerStoreRecord):
    return CuratedOfficialAdapter(
        key="lidl",
        retailer="Lidl",
        directory_url="https://example.invalid/lidl-directory",
        records=(record,),
    )


def test_official_refresh_preserves_promoted_verified_identity_and_records_drift():
    db = _db()
    first = _lidl_record(latitude=50.592225, longitude=7.608542)
    stage_official_store_candidates(db, "56305", (_lidl_adapter(first),))
    candidate = db.query(StoreDiscoveryCandidate).one()
    store = Store(
        retailer="Lidl",
        name="Lidl Puderbach",
        postal_code="56305",
        city="Puderbach",
        address="Urbacherstraße L264",
        latitude=50.592225,
        longitude=7.608542,
        active=True,
        benchmark_verified=False,
        external_id="lidl-puderbach-urbacherstr-l264",
        source_url=first.source_url,
    )
    db.add(store)
    db.flush()
    candidate.matched_store_id = store.id
    candidate.status = "promoted"
    candidate.address_verified = True
    candidate.coordinates_verified = True
    candidate.official_source_verified = True
    candidate.verification_note = "Position manuell im Admin bestätigt"
    db.commit()

    stale = _lidl_record(
        latitude=50.598,
        longitude=7.615,
        source_url="https://example.invalid/lidl-new-source-url",
    )
    created, updated, _ = stage_official_store_candidates(db, "56305", (_lidl_adapter(stale),))
    db.refresh(candidate)

    assert (created, updated) == (0, 1)
    assert candidate.latitude == 50.592225
    assert candidate.longitude == 7.608542
    assert candidate.source_external_id == "lidl-puderbach-urbacherstr-l264"
    assert candidate.status == "promoted"
    assert candidate.matched_store_id == store.id
    assert candidate.address_verified is True
    assert candidate.coordinates_verified is True
    assert candidate.official_source_verified is True
    assert candidate.source_url == "https://example.invalid/lidl-new-source-url"
    assert "Position manuell im Admin bestätigt" in candidate.verification_note
    assert "[source-refresh-drift]" in candidate.verification_note
    assert "50.598000" in candidate.verification_note
    db.close()


def test_official_refresh_still_updates_unverified_candidate_and_reopens_identity_gates():
    db = _db()
    first = _lidl_record(latitude=50.592225, longitude=7.608542)
    stage_official_store_candidates(db, "56305", (_lidl_adapter(first),))
    candidate = db.query(StoreDiscoveryCandidate).one()
    candidate.address_verified = True
    candidate.coordinates_verified = False
    candidate.status = "discovered"
    db.commit()

    # address_verified alone intentionally locks operator-confirmed identity.
    changed = _lidl_record(latitude=50.598, longitude=7.615)
    stage_official_store_candidates(db, "56305", (_lidl_adapter(changed),))
    db.refresh(candidate)
    assert candidate.latitude == 50.592225
    assert candidate.longitude == 7.608542
    assert candidate.address_verified is True
    assert "[source-refresh-drift]" in candidate.verification_note

    # A completely unverified row remains refreshable and follows the source.
    candidate.address_verified = False
    candidate.coordinates_verified = False
    candidate.status = "discovered"
    candidate.verification_note = None
    db.commit()
    stage_official_store_candidates(db, "56305", (_lidl_adapter(changed),))
    db.refresh(candidate)
    assert candidate.latitude == 50.598
    assert candidate.longitude == 7.615
    assert candidate.address_verified is False
    assert candidate.coordinates_verified is False
    assert candidate.status == "discovered"
    db.close()


def test_osm_refresh_preserves_verified_candidate_identity(monkeypatch):
    db = _db()
    candidate = StoreDiscoveryCandidate(
        discovery_key="osm-candidate-1",
        postal_code="56269",
        retailer="ALDI SÜD",
        name="ALDI SÜD Dierdorf",
        address="Bestätigte Adresse 1",
        city="Dierdorf",
        latitude=50.550001,
        longitude=7.650001,
        source="osm",
        source_external_id="node/123",
        source_url="https://example.invalid/old",
        status="verified",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        verification_note="manuell geprüft",
    )
    db.add(candidate)
    db.commit()

    monkeypatch.setattr(
        "app.postcode_coverage_service.discover_postcode_supermarkets",
        lambda postal_code: [
            {
                "discovery_key": "osm-candidate-1",
                "postal_code": postal_code,
                "retailer": "ALDI SÜD",
                "name": "ALDI SÜD Dierdorf",
                "address": "Abweichende Quelle 99",
                "city": "Dierdorf",
                "latitude": 50.56,
                "longitude": 7.66,
                "source": "osm",
                "source_external_id": "node/123",
                "source_url": "https://example.invalid/new",
            }
        ],
    )

    created, updated = stage_postcode_candidates(db, "56269")
    db.refresh(candidate)
    assert (created, updated) == (0, 1)
    assert candidate.address == "Bestätigte Adresse 1"
    assert candidate.latitude == 50.550001
    assert candidate.longitude == 7.650001
    assert candidate.status == "verified"
    assert candidate.address_verified is True
    assert candidate.coordinates_verified is True
    assert candidate.source_url == "https://example.invalid/new"
    assert "[source-refresh-drift]" in candidate.verification_note
    db.close()


def test_puderbach_curated_records_match_reviewed_canonical_identity():
    by_retailer = {
        record.retailer: record
        for record in CURATED_OFFICIAL_STORES
        if record.postal_code == "56305"
    }
    lidl = by_retailer["Lidl"]
    edeka = by_retailer["EDEKA"]

    assert (lidl.latitude, lidl.longitude) == (50.592225, 7.608542)
    assert lidl.external_id == "lidl-puderbach-urbacherstr-l264"
    assert (edeka.latitude, edeka.longitude) == (50.591497, 7.607809)
    assert edeka.external_id == "071378"
