from __future__ import annotations

from app.edeka_multi_source_audit import merge_edeka_sources
from app.web_offer_audit import WebAuditResult, WebOfferRecord


def _row(source: str, name: str, price: float, grams: float | None = None, image: str | None = None):
    return WebOfferRecord(
        retailer="EDEKA",
        store_id=1,
        source_url=f"https://example.invalid/{source}",
        name=name,
        price=price,
        quantity=f"{grams:g} g" if grams is not None else None,
        quantity_value=grams,
        quantity_unit="g" if grams is not None else None,
        packaging_text=f"{grams:g} g" if grams is not None else None,
        image_url=image,
        provenance={"source": "official_store_site" if source == "local" else "central_api"},
    ).validate()


def _result(path: str, rows: list[WebOfferRecord]):
    return WebAuditResult(
        offers=rows,
        source_url=f"https://example.invalid/{path}",
        final_url=f"https://example.invalid/{path}",
        collector_path=path,
        raw_count=len(rows),
        artifacts={},
    )


def test_merge_keeps_central_primary_and_adds_only_missing_local_offers():
    central = _result("central", [
        _row("central", "Bresso Frischkäse", 1.29, 150),
        _row("central", "Himbeeren", 1.99, 125),
    ])
    local = _result("local", [
        _row("local", "Bresso Frischkäse", 1.29, 150, "https://media.smp-it-media.de/products/image/abc"),
        _row("local", "IKEA Gutschein", 50.00),
    ])

    merged = merge_edeka_sources(central, local)

    assert merged.collector_path == "edeka_central_plus_local"
    assert len(merged.offers) == 3
    assert merged.artifacts["source_breakdown"] == {
        "central_count": 2,
        "local_count": 2,
        "source_overlap": 1,
        "central_only": 1,
        "local_only": 1,
        "price_conflicts": 0,
        "unique_combined": 3,
    }
    bresso = next(row for row in merged.offers if row.name == "Bresso Frischkäse")
    assert bresso.price == 1.29
    assert bresso.provenance["sources"] == ["edeka_central", "edeka_local_fellenzer"]
    assert any(row.name == "IKEA Gutschein" for row in merged.offers)


def test_merge_marks_price_conflict_without_silently_overwriting_central_price():
    central = _result("central", [_row("central", "Cola", 1.29, 1500)])
    local = _result("local", [_row("local", "Cola", 1.19, 1500)])

    merged = merge_edeka_sources(central, local)

    assert len(merged.offers) == 1
    assert merged.offers[0].price == 1.29
    assert merged.offers[0].provenance["price_conflict"] is True
    assert merged.artifacts["source_breakdown"]["price_conflicts"] == 1


def test_local_only_source_is_not_required():
    central = _result("central", [_row("central", "Himbeeren", 1.99, 125)])

    merged = merge_edeka_sources(central, None)

    assert len(merged.offers) == 1
    assert merged.artifacts["source_breakdown"]["local_count"] == 0
    assert merged.artifacts["source_breakdown"]["unique_combined"] == 1
