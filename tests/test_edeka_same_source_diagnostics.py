from __future__ import annotations

from app.edeka_web_offer_audit_orchestrator import _same_source_variant_candidates
from app.web_offer_audit import WebOfferRecord


def _row(*, source: str, name: str, price: float, image: str | None = None) -> WebOfferRecord:
    source_url = (
        "https://www.edeka.de/maerkte/071378/angebote/"
        if source == "central"
        else "https://edeka-fellenzer.de/angebote/"
    )
    provenance = (
        {"source": "central_api"}
        if source == "central"
        else {"source": "official_store_site"}
    )
    return WebOfferRecord(
        retailer="EDEKA",
        store_id=1,
        source_url=source_url,
        name=name,
        price=price,
        quantity="125 g",
        quantity_value=125,
        quantity_unit="g",
        packaging_text="125 g",
        image_url=image,
        provenance=provenance,
    ).validate()


def test_same_source_same_name_price_and_image_variant_is_visible_but_not_merged():
    rows = [
        _row(
            source="central",
            name="Himbeeren",
            price=1.79,
            image="https://example.invalid/himbeeren-a.jpg",
        ),
        _row(
            source="central",
            name="Himbeeren",
            price=1.99,
            image="https://example.invalid/himbeeren-b.jpg",
        ),
    ]

    candidates = _same_source_variant_candidates(rows)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["decision"] == "kept_separate"
    assert candidate["reason"] == "same_source_same_name_price_and_image_variant"
    assert candidate["source"] == "central"
    assert candidate["central_price"] == 1.79
    assert candidate["local_price"] == 1.99
    assert candidate["central_name"] == "[Central A] Himbeeren"
    assert candidate["local_name"] == "[Central B] Himbeeren"


def test_same_source_identical_offer_shape_is_not_reported_as_variant():
    rows = [
        _row(source="local", name="Aroma-Pod", price=5.99, image="https://example.invalid/a.jpg"),
        _row(source="local", name="Aroma-Pod", price=5.99, image="https://example.invalid/a.jpg"),
    ]

    assert _same_source_variant_candidates(rows) == []


def test_cross_source_same_name_is_left_to_existing_cross_source_diagnostics():
    rows = [
        _row(source="central", name="Himbeeren", price=1.99, image="https://example.invalid/a.jpg"),
        _row(source="local", name="Himbeeren", price=1.79, image="https://example.invalid/b.jpg"),
    ]

    assert _same_source_variant_candidates(rows) == []
