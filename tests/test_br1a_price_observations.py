from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.data_operations_models import PriceObservation, SourceProduct
from app.db import Base
from app.engine_v140.collectors import CollectedOffer
from app.extractor_adapter import import_collected_offers
from app.lokero_models import NormalPriceObservation
from app.models import CollectionRun, Offer, OfferPriceReference, Store
from app.normal_prices import reference_price_for_offer
from app.price_observations import PriceType, persist_offer_price_observations


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _row(store):
    return CollectedOffer(
        source_key="rewe_br1a", store_name=store.name, retailer=store.retailer,
        product_name="Belastbarer Testkaffee 500 g", category="Kaffee", price=4.49,
        regular_price=6.99, app_price=4.29, quantity=500, unit="g",
        unit_price=8.98, unit_price_unit="kg", valid_from="07.09.2026",
        valid_to="12.09.2026", source_text="Prospekt statt 6,99 € jetzt 4,49 €",
        source_url="https://example.test/rewe", confidence=.99,
    )


def test_offer_reference_and_loyalty_are_append_only_retry_idempotent():
    db = _session()
    store = Store(retailer="REWE", name="BR1A REWE", postal_code="00000", city="Test", address="Test 1")
    db.add(store); db.flush()
    run = CollectionRun(store_id=store.id, source_key="test", status="running")
    db.add(run); db.commit()
    first = import_collected_offers(db, [_row(store)], collection_run_id=run.id)
    second = import_collected_offers(db, [_row(store)], collection_run_id=run.id)
    assert first.price_observations == 3
    assert second.price_observations == 0
    assert {row.price_type for row in db.query(PriceObservation)} == {
        PriceType.PROMOTION.value, PriceType.ADVERTISED_REFERENCE.value, PriceType.LOYALTY.value,
    }
    assert db.query(SourceProduct).count() == 1
    assert db.query(NormalPriceObservation).count() == 0

    offer = db.query(Offer).one()
    product = offer.product
    tomorrow = datetime.utcnow() + timedelta(days=1)
    assert persist_offer_price_observations(
        db, row=_row(store), offer=offer, store=store, product=product,
        collection_run_id=run.id, observed_at=tomorrow,
    ) == 3
    db.commit()
    assert db.query(PriceObservation).count() == 6


def test_same_session_pending_observations_are_retry_idempotent_without_autoflush():
    db = _session()
    store = Store(retailer="EDEKA", name="EDEKA Fellenzer", postal_code="56305", city="Puderbach", address="Test 3")
    db.add(store); db.flush()
    run = CollectionRun(store_id=store.id, source_key="edeka_puderbach:web", status="running")
    db.add(run); db.flush()

    import_collected_offers(db, [_row(store)], collection_run_id=run.id)
    offer = db.query(Offer).one()
    product = offer.product
    db.query(PriceObservation).delete()
    db.flush()

    observed_at = datetime(2026, 9, 10, 3, 30)
    with db.no_autoflush:
        first = persist_offer_price_observations(
            db, row=_row(store), offer=offer, store=store, product=product,
            collection_run_id=run.id, observed_at=observed_at,
        )
        second = persist_offer_price_observations(
            db, row=_row(store), offer=offer, store=store, product=product,
            collection_run_id=run.id, observed_at=observed_at,
        )

    assert first == 3
    assert second == 0
    db.commit()
    assert db.query(PriceObservation).count() == 3


def test_advertised_reference_never_becomes_observed_normal_price():
    db = _session()
    store = Store(retailer="REWE", name="BR1A Ref", postal_code="00000", city="Test", address="Test 2")
    db.add(store); db.commit()
    import_collected_offers(db, [_row(store)])
    offer = db.query(Offer).one()
    reference = db.query(OfferPriceReference).one()
    assert reference.reference_price == 6.99
    assert db.query(PriceObservation).filter_by(price_type="ADVERTISED_REFERENCE").one().price == 6.99
    assert db.query(NormalPriceObservation).count() == 0

    db.delete(reference); db.commit()
    assert reference_price_for_offer(db, offer)["status"] == "unknown"
