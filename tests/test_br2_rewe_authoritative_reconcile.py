from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.authoritative_offer_reconcile import (
    reconcile_completed_rewe_collection,
    reconcile_rewe_authoritative_snapshot,
)
from app.db import Base
from app.engine_v140.collectors import CollectedOffer
from app.extractor_adapter import ImportSummary, normalize_master_key
from app.models import CollectionRun, MasterProduct, Offer, OfferOccurrence, Store


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def _stores(db):
    legacy = Store(
        retailer="REWE",
        name="REWE Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        benchmark_verified=True,
        external_id="321019",
        source_url=None,
    )
    canonical = Store(
        retailer="REWE",
        name="REWE:XL Hundertmark",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Straße 20 - 22",
        active=True,
        benchmark_verified=True,
        external_id="321019",
        source_url="https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
    )
    db.add_all([legacy, canonical])
    db.flush()
    return legacy, canonical


def _product_offer(db, store, name, price, quantity, unit, *, local=True):
    key = normalize_master_key(name, quantity, unit)
    product = MasterProduct(name=name, package_size=f"{quantity:g} {unit}", normalized_key=key)
    db.add(product)
    db.flush()
    offer = Offer(
        store_id=store.id,
        master_product_id=product.id,
        price=price,
        valid_from=date(2026, 9, 7),
        valid_to=date(2026, 9, 13),
        local_store_offer=local,
        source_url="https://www.rewe.de/angebote/dierdorf/321019/test/",
    )
    db.add(offer)
    db.flush()
    return product, offer


def _row(store, name, price, quantity, unit, *, source_text=None):
    return CollectedOffer(
        "rewe-test",
        store.name,
        "REWE",
        name,
        "Sonstiges",
        price,
        quantity=quantity,
        unit=unit,
        valid_from="07.09.2026",
        valid_to="13.09.2026",
        source_text=source_text or f"{name} Aktion {price:.2f} €",
        source_url="https://www.rewe.de/angebote/dierdorf/321019/test/",
        confidence=.99,
    )


def test_complete_snapshot_marks_absent_alias_offer_inactive_without_deleting_history():
    db = _db()
    legacy, canonical = _stores(db)
    _, current = _product_offer(db, canonical, "Crodino Biondo", 4.99, 588, "ml")
    _, stale = _product_offer(db, legacy, "alkoholfrei", 4.99, 6, "x 98 ml")
    occurrence = OfferOccurrence(
        offer_id=stale.id,
        prospect_page=2,
        occurrence_fingerprint="stale-history",
        detail_text="je 6 x 98-ml-Fl.-Pckg.",
        package_size="6 x 98 ml",
        source_text="alte fehlerhafte Zuordnung",
    )
    db.add(occurrence)
    db.commit()

    count = reconcile_rewe_authoritative_snapshot(
        db, canonical, [_row(canonical, "Crodino Biondo", 4.99, 588, "ml")]
    )

    assert count == 1
    assert db.get(Offer, current.id).local_store_offer is True
    assert db.get(Offer, stale.id).local_store_offer is False
    assert db.query(OfferOccurrence).filter_by(offer_id=stale.id).count() == 1
    db.close()


def test_snapshot_fails_closed_when_one_collected_identity_cannot_be_proven():
    db = _db()
    legacy, canonical = _stores(db)
    _, stale = _product_offer(db, legacy, "stale", 1.99, 100, "g")
    db.commit()

    count = reconcile_rewe_authoritative_snapshot(
        db, canonical, [_row(canonical, "not imported", 2.49, 250, "g")]
    )

    assert count is None
    assert db.get(Offer, stale.id).local_store_offer is True
    db.close()


def test_completed_collection_skips_reconciliation_if_any_row_was_rejected():
    db = _db()
    legacy, canonical = _stores(db)
    _, current = _product_offer(db, canonical, "Current", 2.49, 250, "g")
    _, stale = _product_offer(db, legacy, "Stale", 1.99, 100, "g")
    run = CollectionRun(store_id=canonical.id, source_key="rewe:web", status="success")
    db.add(run)
    db.commit()

    rows = [_row(canonical, "Current", 2.49, 250, "g")]
    summary = ImportSummary(received=1, imported=0, rejected_quality=1)
    result = {"offers": rows}

    count = reconcile_completed_rewe_collection(db, canonical, result, summary, run)

    assert count is None
    assert db.get(Offer, current.id).local_store_offer is True
    assert db.get(Offer, stale.id).local_store_offer is True
    refreshed = db.get(CollectionRun, run.id)
    assert refreshed.status == "success"
    assert "authoritative_reconcile=SKIPPED_REJECTIONS" in (refreshed.message or "")
    assert "rejected_quality=1" in (refreshed.message or "")
    db.close()


def test_quality_rejection_persists_exact_row_reason_and_raw_source_without_reconciling():
    db = _db()
    legacy, canonical = _stores(db)
    _, stale = _product_offer(db, legacy, "Stale", 1.99, 100, "g")
    run = CollectionRun(
        store_id=canonical.id,
        source_key="rewe:web",
        status="success",
        message="collector diagnostics stay available",
    )
    db.add(run)
    db.commit()

    rejected = _row(
        canonical,
        "extra",
        4.99,
        588,
        "ml",
        source_text="extra je 6 x 98-ml-Fl.-Pckg. Aktion 4,99 € Dr. Oetker Pizza Tradizionale Salame Romano",
    )
    summary = ImportSummary(received=1, imported=0, rejected_quality=1)

    count = reconcile_completed_rewe_collection(
        db,
        canonical,
        {"offers": [rejected]},
        summary,
        run,
    )

    assert count is None
    assert db.get(Offer, stale.id).local_store_offer is True
    refreshed = db.get(CollectionRun, run.id)
    message = refreshed.message or ""
    assert refreshed.status == "success"
    assert message.startswith("authoritative_reconcile=SKIPPED_REJECTIONS")
    assert "quality_reject[name=extra" in message
    assert "Nur Eigenschaft/Beschreibung, kein identifizierbares Produkt" in message
    assert "Dr. Oetker Pizza Tradizionale Salame Romano" in message
    assert "collector diagnostics stay available" in message
    db.close()


def test_completed_clean_collection_reconciles_and_records_diagnostic():
    db = _db()
    legacy, canonical = _stores(db)
    _product_offer(db, canonical, "Current", 2.49, 250, "g")
    _, stale = _product_offer(db, legacy, "Stale", 1.99, 100, "g")
    run = CollectionRun(store_id=canonical.id, source_key="rewe:web", status="success", message="collector ok")
    db.add(run)
    db.commit()

    rows = [_row(canonical, "Current", 2.49, 250, "g")]
    summary = ImportSummary(received=1, imported=1)
    count = reconcile_completed_rewe_collection(db, canonical, {"offers": rows}, summary, run)

    assert count == 1
    assert db.get(Offer, stale.id).local_store_offer is False
    refreshed = db.get(CollectionRun, run.id)
    assert refreshed.status == "success"
    assert "authoritative_reconciled_inactive=1" in (refreshed.message or "")
    db.close()
