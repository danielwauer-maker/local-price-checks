from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.postcode_reconciliation import deduplicate_candidates, reconcile_postcode_coverage
from app.retailer_store_sources import RetailerSourceResult


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _row(key: str, retailer: str, name: str, address: str, lat: float, lng: float, source: str):
    return StoreDiscoveryCandidate(
        discovery_key=key,
        postal_code="56305",
        retailer=retailer,
        name=name,
        address=address,
        city="Puderbach",
        latitude=lat,
        longitude=lng,
        source=source,
        official_source_verified=source.startswith("official:"),
    )


def _sources():
    return (
        RetailerSourceResult("Lidl", "supported", "fixture", "https://example.invalid/lidl"),
        RetailerSourceResult("EDEKA", "supported", "fixture", "https://example.invalid/edeka"),
    )


def test_puderbach_official_and_osm_rows_collapse_to_two_physical_markets():
    db = _db()
    postcode = CoveragePostalCode(postal_code="56305", city="Puderbach", enabled=True)
    rows = [
        _row(
            "edeka-official", "EDEKA", "EDEKA Fellenzer", "Urbacher Straße 35",
            50.600000, 7.611000, "official:edeka",
        ),
        _row(
            "edeka-osm", "EDEKA", "EDEKA Markt Fellenzer", "Urbacher Straße 30",
            50.593695, 7.607711, "osm",
        ),
        _row(
            "lidl-osm", "Lidl", "Lidl", "Urbacher Straße 31a",
            50.592183, 7.608637, "osm",
        ),
        _row(
            "lidl-official", "Lidl", "Lidl Puderbach", "Urbacherstraße L264",
            50.598000, 7.615000, "official:lidl",
        ),
    ]
    db.add_all([postcode, *rows])
    db.commit()

    visible = deduplicate_candidates(db.query(StoreDiscoveryCandidate).all())
    assert len(visible) == 2
    assert {row.discovery_key for row in visible} == {"edeka-official", "lidl-official"}

    summary = reconcile_postcode_coverage(db, postcode, source_results=_sources())
    assert summary.expected == 2
    assert summary.found == 2
    assert summary.official_verified == 2
    assert summary.additional_discovered == 0
    db.close()


def test_distinct_official_branches_of_same_retailer_are_never_collapsed():
    rows = [
        StoreDiscoveryCandidate(
            discovery_key="rewe-a",
            postal_code="57610",
            retailer="REWE",
            name="PETZ REWE Bahnhofstr. 30",
            address="Bahnhofstr. 30",
            city="Altenkirchen",
            latitude=50.685665,
            longitude=7.638153,
            source="official:rewe",
        ),
        StoreDiscoveryCandidate(
            discovery_key="rewe-b",
            postal_code="57610",
            retailer="REWE",
            name="PETZ REWE Dammweg 10",
            address="Dammweg 10",
            city="Altenkirchen",
            latitude=50.689400,
            longitude=7.646440,
            source="official:rewe",
        ),
    ]
    assert len(deduplicate_candidates(rows)) == 2
