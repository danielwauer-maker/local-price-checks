from app.engine_v140.collectors import CollectedOffer
from app.extractor_adapter import assess_collected_offer


def _row(text: str) -> CollectedOffer:
    return CollectedOffer(
        source_key="test:promo",
        store_name="Testmarkt",
        retailer="EDEKA",
        product_name="Butter Croissants",
        category="Backwaren",
        price=0.49,
        quantity=1,
        unit="stück",
        valid_from="17.08.2026",
        valid_to="23.08.2026",
        source_text=text,
        source_url="https://example.test/prospekt",
        local_store_offer=True,
        confidence=0.99,
    )


def test_valid_three_for_two_complex_offer_passes_canonical_admission():
    assessment = assess_collected_offer(_row("Butter Croissants 3 für 2, je Stück 0,49 €"))
    assert assessment.accepted is True
    assert assessment.rejection is None


def test_invalid_free_item_mechanic_is_rejected_from_public_offer_list():
    assessment = assess_collected_offer(_row("Butter Croissants 3 für 0, je Stück 0,49 €"))
    assert assessment.accepted is False
    assert assessment.rejection == "quality"
