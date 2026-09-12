from scripts.diagnose_external_validation import _offer_summary


def test_offer_summary_exposes_identity_and_price_fields_for_root_cause_analysis():
    row = {
        "id": 42,
        "product_name": "MEINE METZGEREI Hähnchenbrustfilet 1500 g",
        "brand": None,
        "package_size": "1500 g",
        "price": 12.99,
        "unit_price": 8.66,
        "unit_price_unit": "kg",
        "valid_from": "2026-09-07",
        "valid_to": "2026-09-12",
        "occurrence_id": 84,
        "occurrence_package_size": "1,5 kg",
        "occurrence_source_text": "MEINE METZGEREI Hähnchenbrustfilet 1500 g",
    }

    result = _offer_summary(row, 0.73456)

    assert result == {
        "id": 42,
        "similarity": 0.735,
        "product_name": "MEINE METZGEREI Hähnchenbrustfilet 1500 g",
        "brand": None,
        "package_size": "1500 g",
        "price": 12.99,
        "unit_price": 8.66,
        "unit_price_unit": "kg",
        "valid_from": "2026-09-07",
        "valid_to": "2026-09-12",
        "occurrence_id": 84,
        "occurrence_package_size": "1,5 kg",
        "occurrence_source_text": "MEINE METZGEREI Hähnchenbrustfilet 1500 g",
    }
