from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.aldi_live_collector import _prune_stale_aldi_week_offers
from app.db import Base
from app.models import MasterProduct, Offer, OfferOccurrence, OfferPriceReference, Store


def test_prune_removes_only_stale_official_aldi_rows_after_healthy_structured_week():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    store = Store(
        retailer="ALDI SÜD",
        name="ALDI SÜD Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Test",
        active=True,
    )
    safe_product = MasterProduct(name="Rinder-Cevapcici 400 g", normalized_key="safe", package_size="400 g")
    stale_product = MasterProduct(name="Vegan RIO D'ORO", normalized_key="stale", package_size="1,5 l")
    other_product = MasterProduct(name="Other", normalized_key="other", package_size="1 kg")
    db.add_all([store, safe_product, stale_product, other_product])
    db.flush()

    safe_offer = Offer(
        store_id=store.id,
        master_product_id=safe_product.id,
        price=3.99,
        valid_from=date(2026, 9, 7),
        valid_to=date(2026, 9, 13),
        source_url="https://www.aldi-sued.de/angebote",
    )
    stale_offer = Offer(
        store_id=store.id,
        master_product_id=stale_product.id,
        price=0.25,
        valid_from=date(2026, 9, 7),
        valid_to=date(2026, 9, 13),
        source_url="https://www.aldi-sued.de/angebote",
    )
    unrelated_offer = Offer(
        store_id=store.id,
        master_product_id=other_product.id,
        price=1.11,
        valid_from=date(2026, 9, 7),
        valid_to=date(2026, 9, 13),
        source_url="https://example.org/not-aldi",
    )
    db.add_all([safe_offer, stale_offer, unrelated_offer])
    db.flush()
    db.add(OfferOccurrence(
        offer_id=stale_offer.id,
        occurrence_fingerprint="x" * 64,
        source_text="1,69 € + 0,25 € Pfand EINWEG",
    ))
    db.add(OfferPriceReference(offer_id=stale_offer.id, reference_price=1.69, reference_type="regular"))
    db.commit()

    safe_rows = [
        SimpleNamespace(
            product_name="Rinder-Cevapcici 400 g" if i == 0 else f"Safe Product {i} 100 g",
            price=3.99 if i == 0 else float(i + 1),
            valid_from="07.09.2026",
            valid_to="13.09.2026",
        )
        for i in range(20)
    ]

    pruned = _prune_stale_aldi_week_offers(db, store, safe_rows)

    assert pruned == 1
    remaining = {row.id for row in db.query(Offer).all()}
    assert safe_offer.id in remaining
    assert unrelated_offer.id in remaining
    assert stale_offer.id not in remaining
    assert db.query(OfferOccurrence).count() == 0
    assert db.query(OfferPriceReference).count() == 0
