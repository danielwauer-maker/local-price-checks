import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import CollectionRun, MasterProduct, Offer, OfferOccurrence, Store
from app.production_readiness import validate_external_samples
from scripts.validate_external_offers import _load_payload, _offer_rows, _reference_samples


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
    assert payload["evidence"]["sample_policy"] == (
        "Samples must represent weekly promotional offers, not unchanged regular assortment prices."
    )
    assert all(sample["reference_source"].startswith("https://www.marktguru.de/") for sample in payload["samples"])
    assert all(reference.reference_id.startswith("marktguru:") for reference in references)
    assert all(reference.valid_to.isoformat() == "2026-09-12" for reference in references)
    assert all(reference.brand for reference in references)
    assert all(reference.price and reference.price > 0 for reference in references)
    assert all(reference.package_size for reference in references)
    assert all(reference.unit_price and reference.unit_price > 0 for reference in references)
    assert all(reference.unit_price_unit == "kg" for reference in references)


def test_reference_file_maps_to_existing_external_validation_gate():
    payload = _load_payload(REFERENCE_FILE)
    references = _reference_samples(payload)
    offers = [
        {
            "id": idx,
            "product_name": reference.product_name,
            "brand": reference.brand,
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


def test_reference_loader_uses_strict_fields_but_ignores_audit_metadata():
    payload = _load_payload(REFERENCE_FILE)
    references = _reference_samples(payload)

    # Brand is an explicit strict validation field and must influence the gate.
    assert references[0].brand == payload["samples"][0]["brand"]
    assert references[0].reference_id == payload["samples"][0]["reference_id"]

    # Audit provenance remains present in the source file, but it is not part
    # of ExternalOfferSample and therefore cannot influence Collector Primary.
    assert payload["samples"][0]["reference_source"].startswith("https://www.marktguru.de/")
    assert not hasattr(references[0], "reference_source")


def test_reference_loader_rejects_empty_sample_set(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text('{"samples": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty samples"):
        _load_payload(path)


def test_offer_rows_are_limited_to_occurrences_from_the_exact_collection_run():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    started = datetime(2026, 9, 12, 11, 29)
    finished = started + timedelta(minutes=5)
    store = Store(
        retailer="ALDI SÜD",
        name="ALDI SÜD Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Straße 50",
    )
    db.add(store)
    db.flush()
    run = CollectionRun(
        store_id=store.id,
        source_key="aldi",
        started_at=started,
        finished_at=finished,
        status="success",
    )
    db.add(run)
    products = [
        MasterProduct(name="Current", normalized_key="current"),
        MasterProduct(name="Stale", normalized_key="stale"),
    ]
    db.add_all(products)
    db.flush()
    offers = [
        Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=1.99,
            valid_from=date(2026, 9, 7),
            valid_to=date(2026, 9, 12),
            local_store_offer=True,
        )
        for product in products
    ]
    db.add_all(offers)
    db.flush()
    db.add_all(
        [
            OfferOccurrence(
                offer_id=offers[0].id,
                occurrence_fingerprint="current",
                package_size="500 g",
                collected_at=started + timedelta(minutes=1),
            ),
            OfferOccurrence(
                offer_id=offers[1].id,
                occurrence_fingerprint="stale",
                package_size="500 g",
                collected_at=started - timedelta(days=1),
            ),
        ]
    )
    db.commit()

    rows = _offer_rows(
        db,
        store,
        date(2026, 9, 7),
        date(2026, 9, 12),
        run=run,
    )

    assert [row["product_name"] for row in rows] == ["Current"]
    assert rows[0]["occurrence_package_size"] == "500 g"


def test_diagnostic_cli_can_import_app_when_invoked_by_absolute_path(tmp_path):
    script = Path("scripts/diagnose_external_validation.py").resolve()

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Read-only diagnostics" in result.stdout
