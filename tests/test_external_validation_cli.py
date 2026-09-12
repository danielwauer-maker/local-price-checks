from pathlib import Path

import pytest

from app.production_readiness import validate_external_samples
from scripts.validate_external_offers import _load_payload, _reference_samples


REFERENCE_FILE = Path("data/external_validation/aldi-dierdorf-2026-09-12.json")


def test_aldi_dierdorf_reference_file_has_ten_independent_auditable_samples():
    payload = _load_payload(REFERENCE_FILE)
    references = _reference_samples(payload)

    assert len(references) == 10
    assert payload["target"] == {
        "retailer": "ALDI SÜD",
        "city": "Dierdorf",
        "name_contains": "ALDI",
    }
    assert payload["period"] == {"start": "2026-09-07", "end": "2026-09-12"}
    assert "kaufda.de" in payload["evidence"]["local_scope_source"]
    assert "marktguru.de" in payload["evidence"]["offer_detail_source"]
    assert all(sample["reference_source"].startswith("https://www.marktguru.de/") for sample in payload["samples"])
    assert all(reference.valid_to.isoformat() == "2026-09-12" for reference in references)
    assert all(reference.price and reference.price > 0 for reference in references)
    assert all(reference.package_size for reference in references)
    assert all(reference.unit_price and reference.unit_price > 0 for reference in references)


def test_reference_file_maps_to_existing_external_validation_gate():
    payload = _load_payload(REFERENCE_FILE)
    references = _reference_samples(payload)
    offers = [
        {
            "id": idx,
            "product_name": reference.product_name,
            "package_size": reference.package_size,
            "price": reference.price,
            "unit_price": reference.unit_price,
            "unit_price_unit": reference.unit_price_unit,
            "valid_to": reference.valid_to,
            "local_store_offer": True,
            "image_present": True,
        }
        for idx, reference in enumerate(references, start=1)
    ]

    result = validate_external_samples(references, offers, min_samples=10)

    assert result.status == "PASS"
    assert result.checked == 10
    assert result.matched == 10
    assert result.missing == 0
    assert result.online_only_leaks == 0
    assert result.score == 100.0


def test_reference_loader_does_not_trust_evidence_metadata_as_validation_fields():
    payload = _load_payload(REFERENCE_FILE)
    references = _reference_samples(payload)

    # Audit metadata such as reference_brand/source is deliberately separate
    # from the strict matching schema. Only explicitly supported fields can
    # influence the Collector Primary gate.
    assert references[0].brand is None
    assert references[0].reference_id.startswith("marktguru:")


def test_reference_loader_rejects_empty_sample_set(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text('{"samples": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty samples"):
        _load_payload(path)
