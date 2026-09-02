from datetime import date

import pytest

from app import edeka_live_collector
from app.collection_service import CollectionError
from app.models import Store
from app.web_offer_audit import WebAuditResult, WebOfferRecord


def _store():
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


def _result(*, completeness="complete", local_status="success"):
    offer = WebOfferRecord(
        retailer="EDEKA",
        store_id=20,
        source_url="https://www.edeka.de/maerkte/071378/angebote/",
        name="Himbeeren",
        price=1.79,
        quantity="125g",
        quantity_value=125,
        quantity_unit="g",
        packaging_text="125g",
        valid_from=date(2026, 8, 31),
        valid_to=date(2026, 9, 5),
        category="Obst & Gemüse",
        image_url="https://example.invalid/himbeeren.jpg",
        provenance={"sources": ["edeka_central"]},
    ).validate()
    return WebAuditResult(
        offers=[offer],
        source_url=offer.source_url,
        final_url=offer.source_url,
        collector_path="edeka_central_plus_local",
        raw_count=1,
        status="success",
        artifacts={
            "central_completeness_status": completeness,
            "source_breakdown": {
                "central_completeness": completeness,
                "local_status": local_status,
                "central_count": 224,
                "local_count": 73,
                "unique_combined": 248,
            },
        },
    )


def test_live_collector_converts_complete_audit_to_normal_collected_offers(monkeypatch):
    monkeypatch.setattr(edeka_live_collector, "fetch_combined_edeka", lambda store: _result())

    payload = edeka_live_collector._collect_result(_store())

    assert payload["fetch_mode"] == "edeka_central_plus_local"
    assert len(payload["offers"]) == 1
    row = payload["offers"][0]
    assert row.store_name == "EDEKA Fellenzer"
    assert row.retailer == "EDEKA"
    assert row.product_name == "Himbeeren"
    assert row.price == 1.79
    assert row.valid_from == "2026-08-31"
    assert row.valid_to == "2026-09-05"
    assert row.local_store_offer is True
    assert "edeka_central" in row.source_text


def test_live_collector_rejects_partial_central_source(monkeypatch):
    monkeypatch.setattr(
        edeka_live_collector,
        "fetch_combined_edeka",
        lambda store: _result(completeness="partial"),
    )

    with pytest.raises(CollectionError, match="Zentralquelle nicht vollständig"):
        edeka_live_collector._collect_result(_store())


def test_fellenzer_live_collector_rejects_missing_local_supplement(monkeypatch):
    monkeypatch.setattr(
        edeka_live_collector,
        "fetch_combined_edeka",
        lambda store: _result(local_status="partial"),
    )

    with pytest.raises(CollectionError, match="lokale Ergänzungsquelle"):
        edeka_live_collector._collect_result(_store())
