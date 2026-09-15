from __future__ import annotations

from datetime import date

import pytest

from app import edeka_live_collector
from app.collection_service import CollectionError
from app.models import Store
from app.web_offer_audit import WebAuditResult, WebOfferRecord


def _store() -> Store:
    return Store(
        id=20,
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 35",
        external_id="071378",
        source_url="https://www.edeka.de/maerkte/071378/",
        active=True,
        benchmark_verified=False,
    )


def _offer(name: str, valid_from: date, valid_to: date) -> WebOfferRecord:
    return WebOfferRecord(
        retailer="EDEKA",
        store_id=20,
        source_url="https://www.edeka.de/maerkte/071378/angebote/",
        name=name,
        price=1.79,
        quantity="125g",
        quantity_value=125,
        quantity_unit="g",
        packaging_text="125g",
        valid_from=valid_from,
        valid_to=valid_to,
        category="Obst & Gemüse",
        image_url="https://example.invalid/product.jpg",
        provenance={"sources": ["edeka_central"]},
    ).validate()


def _artifacts() -> dict:
    return {
        "market_page_id": "071378",
        "central_completeness_status": "complete",
        "source_breakdown": {
            "central_completeness": "complete",
            "local_status": "success",
            "central_count": 3,
            "local_count": 1,
            "unique_combined": 3,
        },
    }


def test_fellenzer_scope_keeps_current_and_next_week_and_discards_far_future(monkeypatch):
    monkeypatch.setattr(edeka_live_collector, "app_today", lambda: date(2026, 9, 15))
    current = _offer("Aktuelle Woche", date(2026, 9, 14), date(2026, 9, 19))
    next_week = _offer("Nächste Woche", date(2026, 9, 21), date(2026, 9, 26))
    far_future = _offer("Übernächste Woche", date(2026, 9, 28), date(2026, 10, 3))

    selected = edeka_live_collector._validate_live_scope(
        _store(),
        [current, next_week, far_future],
        _artifacts(),
    )

    assert selected == [current, next_week]


def test_fellenzer_scope_still_rejects_stale_rows(monkeypatch):
    monkeypatch.setattr(edeka_live_collector, "app_today", lambda: date(2026, 9, 15))
    current = _offer("Aktuelle Woche", date(2026, 9, 14), date(2026, 9, 19))
    stale = _offer("Altbestand", date(2026, 9, 7), date(2026, 9, 12))

    with pytest.raises(CollectionError, match="nicht aktuell gebundene Angebote"):
        edeka_live_collector._validate_live_scope(
            _store(),
            [current, stale],
            _artifacts(),
        )


def test_fellenzer_scope_requires_at_least_one_offer_active_today(monkeypatch):
    monkeypatch.setattr(edeka_live_collector, "app_today", lambda: date(2026, 9, 15))
    next_week = _offer("Nächste Woche", date(2026, 9, 21), date(2026, 9, 26))

    with pytest.raises(CollectionError, match="keine Angebote für 2026-09-15"):
        edeka_live_collector._validate_live_scope(
            _store(),
            [next_week],
            _artifacts(),
        )


def test_collect_result_reports_current_and_next_week_counts(monkeypatch):
    monkeypatch.setattr(edeka_live_collector, "app_today", lambda: date(2026, 9, 15))
    current = _offer("Aktuelle Woche", date(2026, 9, 14), date(2026, 9, 19))
    next_week = _offer("Nächste Woche", date(2026, 9, 21), date(2026, 9, 26))
    far_future = _offer("Übernächste Woche", date(2026, 9, 28), date(2026, 10, 3))
    artifacts = _artifacts()
    audit = WebAuditResult(
        offers=[current, next_week, far_future],
        source_url=current.source_url,
        final_url=current.source_url,
        collector_path="edeka_central_plus_local",
        raw_count=3,
        status="success",
        artifacts=artifacts,
    )
    monkeypatch.setattr(edeka_live_collector, "fetch_combined_edeka", lambda store: audit)

    payload = edeka_live_collector._collect_result(_store())

    assert payload["current_offer_count"] == 1
    assert payload["next_week_offer_count"] == 1
    assert payload["selected_offer_count"] == 2
    assert payload["out_of_horizon_offers_discarded"] == 1
    assert [row.product_name for row in payload["offers"]] == ["Aktuelle Woche", "Nächste Woche"]
