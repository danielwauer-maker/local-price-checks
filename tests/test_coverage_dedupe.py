from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.coverage_models import CoverageRegion
from app.coverage_service import coverage_payload
from app.db import Base
from app.models import MasterProduct, Offer, Store


def test_coverage_counts_identical_offer_once_across_two_markets():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    suffix = uuid4().hex[:10]
    region = CoverageRegion(
        name=f"Dedupe Testregion {suffix}",
        postal_code="57614",
        city="Steimel",
        center_lat=50.6199,
        center_lng=7.6264,
        radius_km=50,
        status="building",
        active=True,
    )
    db.add(region)
    product = MasterProduct(name="Dedupe Testartikel", normalized_key=f"coverage-dedupe-test-{suffix}")
    db.add(product)
    db.flush()
    stores = []
    for idx in range(2):
        store = Store(
            retailer="Netto Marken-Discount",
            name=f"Dedupe Netto {suffix} {idx}",
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
