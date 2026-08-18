from datetime import date, timedelta

from app.coverage_models import CoverageRegion
from app.coverage_service import coverage_payload
from app.db import Base, SessionLocal, engine
from app.models import MasterProduct, Offer, Store


def test_coverage_counts_identical_offer_once_across_two_markets():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    region = CoverageRegion(
        name="Dedupe Testregion",
        postal_code="57614",
        city="Steimel",
        center_lat=50.6199,
        center_lng=7.6264,
        radius_km=50,
        status="building",
        active=True,
    )
    db.add(region)
    product = MasterProduct(name="Dedupe Testartikel", normalized_key="coverage-dedupe-test")
    db.add(product)
    db.flush()
    stores = []
    for idx in range(2):
        store = Store(
            retailer="Netto Marken-Discount",
            name=f"Dedupe Netto {idx}",
            postal_code="57614",
            city="Steimel",
            address=f"Testweg {idx}",
            latitude=50.62 + idx * 0.001,
            longitude=7.63 + idx * 0.001,
            active=True,
            benchmark_verified=True,
        )
        db.add(store)
        db.flush()
        stores.append(store)
    today = date.today()
    for store in stores:
        db.add(Offer(
            store_id=store.id,
            master_product_id=product.id,
            price=1.99,
            unit_price=3.98,
            unit_price_unit="kg",
            valid_from=today,
            valid_to=today + timedelta(days=6),
            local_store_offer=True,
        ))
    db.commit()
    payload = coverage_payload(db, region)
    assert payload["currentOfferRows"] == 2
    assert payload["currentOffers"] == 1

    for store in stores:
        db.query(Offer).filter(Offer.store_id == store.id).delete()
        db.delete(store)
    db.delete(product)
    db.delete(region)
    db.commit()
    db.close()
