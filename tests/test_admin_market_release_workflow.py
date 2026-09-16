from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.admin_candidate_coordinate_routes import _queue_candidate
from app.admin_coverage_routes import _activation_rows_for_postcode
from app.coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.models import Store
from app.postcode_reconciliation import group_physical_candidates, reconcile_postcode_coverage
from app.retailer_store_sources import RetailerSourceResult


TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _candidate(key: str, *, retailer: str = "EDEKA", address: str = "Urbacher Straße 31a", **overrides):
    values = {
        "discovery_key": key,
        "postal_code": "56305",
        "retailer": retailer,
        "name": f"{retailer} Testmarkt",
        "address": address,
        "city": "Puderbach",
        "latitude": 50.592267,
        "longitude": 7.608759,
        "source": "osm",
    }
    values.update(overrides)
    return StoreDiscoveryCandidate(**values)


def _source(status: str) -> tuple[RetailerSourceResult, ...]:
    return (RetailerSourceResult("Lidl", status, "fixture", "https://example.invalid"),)


def test_empty_active_postcode_is_no_known_stores_even_when_source_adapter_is_incomplete():
    db = _db()
    postcode = CoveragePostalCode(postal_code="57614", city="Fluterschen", enabled=True)
    db.add(postcode)
    db.commit()

    summary = reconcile_postcode_coverage(db, postcode, source_results=_source("source_unavailable"))

    assert summary.expected == 0
    assert summary.found == 0
    assert summary.status == "no_known_stores"
    assert summary.status_label == "Keine Märkte bekannt"
    db.close()


def test_fully_verified_postcode_is_not_downgraded_by_adapter_health():
    db = _db()
    postcode = CoveragePostalCode(postal_code="56305", city="Puderbach", enabled=True)
    candidate = _candidate(
        "official-lidl",
        source="official:lidl",
        source_external_id="lidl-56305",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="promoted",
    )
    store = Store(
        retailer="EDEKA",
        name="EDEKA Puderbach",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 31a",
        latitude=50.592267,
        longitude=7.608759,
        external_id="lidl-56305",
        active=True,
        benchmark_verified=False,
    )
    db.add_all([postcode, candidate, store])
    db.flush()
    candidate.matched_store_id = store.id
    db.commit()

    summary = reconcile_postcode_coverage(
        db,
        postcode,
        source_results=_source("manual_verification_required"),
    )

    assert summary.found == 1
    assert summary.promoted == 1
    assert summary.status == "complete"
    assert summary.status_label == "Vollständig verifiziert"
    db.close()


def test_matching_legacy_store_does_not_count_as_promoted_without_explicit_candidate_link():
    db = _db()
    postcode = CoveragePostalCode(postal_code="56305", city="Puderbach", enabled=True)
    candidate = _candidate(
        "official-lidl-unlinked",
        source="official:lidl",
        source_external_id="lidl-puderbach-legacy",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="verified",
    )
    legacy_store = Store(
        retailer="EDEKA",
        name="EDEKA Puderbach",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 31a",
        latitude=50.592267,
        longitude=7.608759,
        external_id="lidl-puderbach-legacy",
        active=True,
        benchmark_verified=False,
    )
    db.add_all([postcode, candidate, legacy_store])
    db.commit()

    summary = reconcile_postcode_coverage(
        db,
        postcode,
        source_results=_source("manual_verification_required"),
    )

    assert summary.found == 1
    assert summary.address_verified == 1
    assert summary.coordinates_verified == 1
    assert summary.official_verified == 1
    assert summary.promoted == 0
    assert summary.status == "verification_pending"
    assert summary.status_label == "Verifikation ausstehend"
    db.close()


def test_coordinate_queue_uses_one_card_per_physical_market_and_prefers_verified_member():
    official = _candidate(
        "official-lidl",
        source="official:lidl",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
    )
    osm = _candidate(
        "osm-lidl",
        source="osm",
        address_verified=False,
        coordinates_verified=False,
        official_source_verified=False,
    )

    groups = group_physical_candidates([osm, official])
    assert len(groups) == 1

    row, ready = _queue_candidate(groups[0])
    assert ready is True
    assert row is official
    assert row.address_verified is True
    assert row.coordinates_verified is True


def test_activation_rows_keep_unpromoted_market_visible_and_surface_orphan_store():
    candidates = [
        _candidate("lidl", retailer="Lidl", address="Urbacher Straße 31a"),
        _candidate("edeka", retailer="EDEKA", address="Urbacher Straße 35", latitude=50.593),
    ]
    linked = Store(
        retailer="Lidl",
        name="Lidl Puderbach",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 31a",
        latitude=50.592267,
        longitude=7.608759,
        active=True,
    )
    orphan = Store(
        retailer="REWE",
        name="Alter Store ohne Candidate",
        postal_code="56305",
        city="Puderbach",
        address="Andere Straße 10",
        latitude=50.60,
        longitude=7.61,
        active=True,
    )
    linked.id = 10
    orphan.id = 11

    rows = _activation_rows_for_postcode(candidates, [linked, orphan])

    assert len(rows) == 3
    assert any(row["candidate"].retailer == "EDEKA" and row["store"] is None for row in rows if row["candidate"])
    assert any(row["store"] is linked and not row["orphan_store"] for row in rows)
    assert any(row["store"] is orphan and row["orphan_store"] for row in rows)


def test_shared_sidebar_uses_general_sibling_layout_not_fragile_direct_sibling():
    sidebar = (TEMPLATES / "admin_sidebar.html").read_text(encoding="utf-8")
    assert ".admin-sidebar ~ .wrap" in sidebar
    assert ".admin-sidebar + .wrap" not in sidebar
    assert "width:calc(100% - 292px)!important" in sidebar


def test_coverage_activation_ui_explains_next_steps_and_uses_found_as_promotion_denominator():
    template = (TEMPLATES / "admin_coverage.html").read_text(encoding="utf-8")
    assert "activation_rows_by_postcode" in template
    assert "Nächster Schritt: Test-Scrape starten." in template
    assert "Nächster Schritt: Quality Gate prüfen." in template
    assert "Nächster Schritt: Markt veröffentlichen." in template
    assert "Promoted: ${p.promoted}/${p.found}" in template
    assert "Beta-Zielmarkt" in template
    assert "Außerhalb Beta" in template
    assert "Beta-Onboarding-Kennzahlen" in template
