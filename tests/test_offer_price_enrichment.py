from datetime import datetime, timedelta

from app.api_routes import _price_payload
from app.clock import app_today
from app.db import Base, SessionLocal, engine
from app.lokero_models import NormalPriceObservation
from app.models import MasterProduct, Offer, OfferOccurrence, OfferPriceReference, Store
from app.normal_prices import reference_price_for_offer, reference_prices_for_offers


def _setup_offer(*, price=0.49):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    store = db.query(Store).filter_by(name="Promotion API Testmarkt").first()
    if not store:
        store = Store(
            retailer="Lidl",
            name="Promotion API Testmarkt",
            postal_code="00000",
            city="Test",
            address="Test 1",
            active=True,
            benchmark_verified=True,
        )
        db.add(store)
        db.flush()
    product = db.query(MasterProduct).filter_by(normalized_key="promotion-api-test-product").first()
    if not product:
        product = MasterProduct(name="Croissants", normalized_key="promotion-api-test-product")
        db.add(product)
        db.flush()
    today = app_today()
    offer = (
        db.query(Offer)
        .filter_by(store_id=store.id, master_product_id=product.id, valid_from=today, price=price)
        .first()
    )
    if not offer:
        offer = Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=price,
            valid_from=today,
            valid_to=today + timedelta(days=6),
            local_store_offer=True,
        )
        db.add(offer)
        db.flush()
    db.query(OfferOccurrence).filter(OfferOccurrence.offer_id == offer.id).delete()
    db.query(OfferPriceReference).filter(OfferPriceReference.offer_id == offer.id).delete()
    db.commit()
    return db, offer


def test_price_payload_exposes_explicit_reference_and_discount():
    db, offer = _setup_offer(price=1.49)
    db.add(OfferPriceReference(
        offer_id=offer.id,
        reference_price=1.99,
        reference_type="regular",
        discount_percent=25.1,
    ))
    db.commit()
    payload = _price_payload(offer, db)
    assert payload["referencePrice"] == 1.99
    assert payload["referenceType"] == "regular"
    assert payload["referencePriceEstimated"] is False
    assert payload["discountPercent"] == 25.1
    db.close()


def test_price_payload_marks_inferred_reference_price():
    db, offer = _setup_offer(price=1.49)
    db.add(OfferPriceReference(
        offer_id=offer.id,
        reference_price=1.99,
        reference_type="inferred_discount",
        discount_percent=25.0,
    ))
    db.commit()
    payload = _price_payload(offer, db)
    assert payload["referencePrice"] == 1.99
    assert payload["referencePriceEstimated"] is True
    db.close()


def test_price_payload_exposes_three_for_two_bundle_semantics():
    db, offer = _setup_offer(price=0.49)
    db.add(OfferOccurrence(
        offer_id=offer.id,
        prospect_page=3,
        occurrence_fingerprint="promotion-api-three-for-two",
        source_text="PDF Seite 3: Croissants 3 für 2, je 0,49 €",
    ))
    db.commit()
    payload = _price_payload(offer, db)
    promotion = payload["promotion"]
    assert promotion["kind"] == "free_item"
    assert promotion["buyQuantity"] == 3
    assert promotion["payQuantity"] == 2
    assert promotion["bundlePrice"] == 0.98
    assert promotion["regularBundlePrice"] == 1.47
    assert promotion["savingsAmount"] == 0.49
    assert payload["discountPercent"] == 33.3
    db.close()


def test_price_payload_exposes_lidl_plus_without_replacing_normal_offer():
    db, offer = _setup_offer(price=3.99)
    db.add(OfferOccurrence(
        offer_id=offer.id,
        prospect_page=13,
        occurrence_fingerprint="promotion-api-lidl-plus",
        source_text=(
            "PDF Seite 13: Dr. Oetker Ristorante Pizza 3,99 € "
            "SPECIAL_PRICE kind=lidl_plus label=Lidl Plus price=3.79"
        ),
    ))
    db.commit()
    payload = _price_payload(offer, db)
    promotion = payload["promotion"]
    assert payload["offer"]["price"] == 3.99
    assert promotion["kind"] == "lidl_plus"
    assert promotion["bundlePrice"] == 3.99
    assert promotion["specialPrice"] == 3.79
    assert "3,79" in promotion["label"]
    db.close()


def test_price_payload_exposes_minimum_quantity_tier_separately():
    db, offer = _setup_offer(price=1.99)
    db.add(OfferOccurrence(
        offer_id=offer.id,
        prospect_page=1,
        occurrence_fingerprint="promotion-api-tier",
        source_text="PDF Seite 1: Original Wagner 1,99 € AB 3 STÜCK 1,66 €",
    ))
    db.commit()
    payload = _price_payload(offer, db)
    promotion = payload["promotion"]
    assert payload["offer"]["price"] == 1.99
    assert promotion["kind"] == "tier_price"
    assert promotion["specialPrice"] == 1.66
    assert promotion["minimumQuantity"] == 3
    db.close()


def test_bulk_reference_price_preserves_scalar_priority_and_payload():
    db, offer = _setup_offer(price=1.49)
    db.query(NormalPriceObservation).filter(
        NormalPriceObservation.master_product_id == offer.master_product_id,
    ).delete(synchronize_session=False)
    db.add_all([
        NormalPriceObservation(
            master_product_id=offer.master_product_id,
            store_id=offer.store_id,
            retailer=offer.store.retailer,
            price=2.09,
            source="test_store_history",
            confidence=1.0,
            is_regular_price=True,
            observed_at=datetime.utcnow(),
        ),
        NormalPriceObservation(
            master_product_id=offer.master_product_id,
            retailer=offer.store.retailer,
            price=2.49,
            source="test_retailer_history",
            confidence=1.0,
            is_regular_price=True,
            observed_at=datetime.utcnow(),
        ),
    ])
    db.commit()

    scalar = reference_price_for_offer(db, offer)
    assert reference_prices_for_offers(db, [offer])[offer.id] == scalar
    assert scalar["source"] == "store_history"

    db.add(OfferPriceReference(
        offer_id=offer.id,
        reference_price=1.99,
        reference_type="regular",
        discount_percent=25.1,
    ))
    db.commit()
    scalar = reference_price_for_offer(db, offer)
    assert reference_prices_for_offers(db, [offer])[offer.id] == scalar
    assert scalar["source"] == "regular"
    db.close()
