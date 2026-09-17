from __future__ import annotations

from pathlib import Path

import app.admin_coverage_routes as coverage_routes
from app.coverage_models import StoreDiscoveryCandidate
from app.models import Store


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


def _candidate(
    *,
    key: str,
    retailer: str,
    name: str,
    address: str,
    city: str,
    latitude: float,
    longitude: float,
    source: str,
    source_external_id: str | None = None,
    matched_store_id: int | None = None,
) -> StoreDiscoveryCandidate:
    return StoreDiscoveryCandidate(
        discovery_key=key,
        postal_code="56587",
        retailer=retailer,
        name=name,
        address=address,
        city=city,
        latitude=latitude,
        longitude=longitude,
        source=source,
        source_external_id=source_external_id,
        status="discovered",
        address_verified=False,
        coordinates_verified=False,
        official_source_verified=False,
        matched_store_id=matched_store_id,
    )


def _rewe_store(store_id: int, name: str) -> Store:
    return _store(
        store_id,
        "REWE",
        name,
        "Kirschbüchel 2",
        "Straßenhaus",
        50.542010,
        7.519868,
        "1940425",
    )


def _rewe_candidate(*, matched_store_id: int | None = None, source: str = "official:rewe"):
    return _candidate(
        key=f"rewe-{source}-{matched_store_id}",
        retailer="REWE",
        name="REWE Dennis Weirich",
        address="Kirschbüchel 2",
        city="Straßenhaus",
        latitude=50.542010,
        longitude=7.519868,
        source=source,
        source_external_id="1940425" if source.startswith("official:") else "way/rewe",
        matched_store_id=matched_store_id,
    )


def test_matching_legacy_store_does_not_make_unpromoted_candidate_look_promoted():
    candidate = _candidate(
        key="aldi-osm",
        retailer="ALDI SÜD",
        name="ALDI Süd",
        address="Über dem Stellweg 5",
        city="Oberhonnefeld-Gierend",
        latitude=50.558756,
        longitude=7.527580,
        source="osm",
        source_external_id="way/49996568",
    )
    legacy_store = _store(
        6,
        "ALDI SÜD",
        "ALDI SÜD Oberhonnefeld-Gierend",
        "Über dem Stellweg 5",
        "Oberhonnefeld-Gierend",
        50.555,
        7.52,
    )

    rows = coverage_routes._activation_rows_for_postcode([candidate], [legacy_store])

    discovery = rows[0]
    orphan = rows[1]
    assert discovery["candidate"] is candidate
    assert discovery["store"] is None
    assert discovery["explicitly_promoted"] is False
    assert discovery["assignment_conflict"] is False
    assert orphan["candidate"] is None
    assert orphan["store"].id == 6
    assert orphan["orphan_store"] is True
    assert orphan["explicitly_promoted"] is False


def test_56587_promoted_rewe_uses_explicit_store_2_and_leaves_store_15_orphaned():
    candidate = _rewe_candidate(matched_store_id=2)
    canonical = _rewe_store(2, "REWE Straßenhaus")
    duplicate = _rewe_store(15, "REWE Dennis Weirich")

    rows = coverage_routes._activation_rows_for_postcode(
        [candidate],
        [canonical, duplicate],
    )

    promoted = rows[0]
    orphan = rows[1]
    assert promoted["candidate"] is candidate
    assert promoted["store"].id == 2
    assert promoted["explicitly_promoted"] is True
    assert promoted["orphan_store"] is False
    assert promoted["assignment_conflict"] is False
    assert orphan["store"].id == 15
    assert orphan["orphan_store"] is True
    assert orphan["explicitly_promoted"] is False


def test_duplicate_matching_legacy_rewe_stores_are_not_arbitrarily_selected_before_promotion():
    candidate = _rewe_candidate()
    canonical = _rewe_store(2, "REWE Straßenhaus")
    duplicate = _rewe_store(15, "REWE Dennis Weirich")

    rows = coverage_routes._activation_rows_for_postcode(
        [candidate],
        [canonical, duplicate],
    )

    assert rows[0]["store"] is None
    assert rows[0]["explicitly_promoted"] is False
    orphan_ids = {row["store"].id for row in rows[1:] if row["orphan_store"]}
    assert orphan_ids == {2, 15}


def test_conflicting_explicit_store_ids_for_one_physical_market_fail_closed():
    official = _rewe_candidate(matched_store_id=2, source="official:rewe")
    osm = _rewe_candidate(matched_store_id=15, source="osm")
    canonical = _rewe_store(2, "REWE Straßenhaus")
    duplicate = _rewe_store(15, "REWE Dennis Weirich")

    rows = coverage_routes._activation_rows_for_postcode(
        [official, osm],
        [canonical, duplicate],
    )

    conflict = rows[0]
    assert conflict["store"] is None
    assert conflict["explicitly_promoted"] is False
    assert conflict["assignment_conflict"] is True
    assert conflict["conflicting_store_ids"] == [2, 15]
    assert "Mehrere explizite Store-Zuordnungen" in conflict["conflict_reason"]
    orphan_ids = {row["store"].id for row in rows[1:] if row["orphan_store"]}
    assert orphan_ids == {2, 15}


def test_explicit_assignment_to_store_outside_current_postcode_fails_closed():
    candidate = _rewe_candidate(matched_store_id=99)
    local_store = _rewe_store(2, "REWE Straßenhaus")

    rows = coverage_routes._activation_rows_for_postcode([candidate], [local_store])

    conflict = rows[0]
    assert conflict["store"] is None
    assert conflict["assignment_conflict"] is True
    assert conflict["conflicting_store_ids"] == [99]
    assert "in dieser PLZ nicht vorhanden" in conflict["conflict_reason"]
    assert rows[1]["store"].id == 2
    assert rows[1]["orphan_store"] is True


def test_coverage_template_never_labels_orphan_store_as_promoted():
    template = (
        Path(coverage_routes.__file__).resolve().parent
        / "templates"
        / "admin_coverage.html"
    ).read_text(encoding="utf-8")

    assert "Promoted {{ '✓' if row.explicitly_promoted else '✗' }}" in template
    assert "a.can_test_scrape and row.explicitly_promoted" in template
    assert "a.can_publish and row.explicitly_promoted" in template
    assert "Zuordnungskonflikt" in template
