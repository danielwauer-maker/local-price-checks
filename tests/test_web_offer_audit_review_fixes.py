from __future__ import annotations

from datetime import date
import inspect

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.engine_v140.browser_fetch import browser_fetch
from app.models import MasterProduct, Offer, ProductBarcode, Store
from app import web_offer_audit_runtime as runtime
from app.web_offer_audit import WebOfferRecord


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _store(retailer="EDEKA", external_id="071378"):
    return Store(
        retailer=retailer,
        name=f"{retailer} Review Test",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 35",
        external_id=external_id,
        source_url="https://www.edeka.de/maerkte/071378/angebote/",
        active=True,
    )


def test_comparison_uses_only_same_week_and_one_to_one_matching(monkeypatch):
    monkeypatch.setattr(runtime, "app_today", lambda: date(2026, 9, 1))
    db = _db()
    store = _store()
    product = MasterProduct(brand="Molkerei", name="Testmilch", package_size="1 l", normalized_key="testmilch")
    db.add_all([store, product])
    db.flush()
    db.add(ProductBarcode(barcode="4000000000001", master_product_id=product.id, source="fixture"))
    # One in-period offer and two irrelevant historical/future rows.
    db.add_all([
        Offer(store_id=store.id, master_product_id=product.id, price=1.29, valid_from=date(2026, 8, 31), valid_to=date(2026, 9, 5)),
        Offer(store_id=store.id, master_product_id=product.id, price=1.39, valid_from=date(2026, 8, 18), valid_to=date(2026, 8, 23)),
        Offer(store_id=store.id, master_product_id=product.id, price=1.19, valid_from=date(2026, 9, 14), valid_to=date(2026, 9, 19)),
    ])
    db.commit()

    web = WebOfferRecord(
        "EDEKA", store.id, store.source_url, "Testmilch", brand="Molkerei",
        ean="4000000000001", price=1.29, quantity="1 l", quantity_value=1,
        quantity_unit="l", packaging_text="1 l", valid_from=date(2026, 8, 31), valid_to=date(2026, 9, 5),
    ).validate()
    result = runtime._comparison(db, store, [web], "current")
    assert result["period_start"] == "2026-08-31"
    assert result["period_end"] == "2026-09-06"
    assert result["prospect_count"] == 1
    assert result["matched"] == 1
    assert result["price_match"] == 1
    assert result["price_mismatch"] == 0
    db.close()


def test_comparison_never_matches_one_web_offer_twice(monkeypatch):
    monkeypatch.setattr(runtime, "app_today", lambda: date(2026, 9, 1))
    db = _db()
    store = _store()
    product = MasterProduct(brand="Marke", name="Kaffee", package_size="500 g", normalized_key="kaffee")
    db.add_all([store, product])
    db.flush()
    db.add_all([
        Offer(store_id=store.id, master_product_id=product.id, price=4.99, valid_from=date(2026, 8, 31), valid_to=date(2026, 9, 5)),
        Offer(store_id=store.id, master_product_id=product.id, price=5.49, valid_from=date(2026, 9, 1), valid_to=date(2026, 9, 6)),
    ])
    db.commit()
    web = WebOfferRecord(
        "EDEKA", store.id, store.source_url, "Kaffee", brand="Marke", price=4.99,
        quantity="500 g", quantity_value=500, quantity_unit="g", packaging_text="500 g",
        valid_from=date(2026, 8, 31), valid_to=date(2026, 9, 6),
    ).validate()
    result = runtime._comparison(db, store, [web], "current")
    assert result["prospect_count"] == 2
    assert result["matched"] == 1
    assert result["price_match"] + result["price_mismatch"] == 1
    assert result["prospect_only"] == 1
    db.close()


def test_period_filter_uses_overlap_not_only_valid_from(monkeypatch):
    monkeypatch.setattr(runtime, "app_today", lambda: date(2026, 9, 1))
    crossing = WebOfferRecord(
        "EDEKA", 1, "https://www.edeka.de", "Wochenwechsel", price=1.99,
        valid_from=date(2026, 8, 29), valid_to=date(2026, 9, 2),
    )
    assert runtime.offer_overlaps_period(crossing, "current") is True


def test_penny_context_requires_selected_store_evidence():
    store = _store("PENNY", "4030882")
    store.postal_code = "10115"
    store.city = "Berlin"
    assert runtime._strong_penny_context_match(
        store,
        '<div class="market selected active">PENNY Markt 10115 Berlin</div>',
        [],
    ) is True
    # Merely finding the expected ID somewhere in an all-markets payload is not
    # evidence that this market is selected.  The audit must fail closed here.
    assert runtime._strong_penny_context_match(
        store,
        '<div class="market selected active">PENNY Markt 80331 München</div>',
        [{"data": {"allMarkets": [{"id": "4030882"}, {"id": "830784"}]}}],
    ) is False
    assert runtime._strong_penny_context_match(store, "<html></html>", []) is False


def test_browser_deep_drain_is_opt_in_by_default():
    signature = inspect.signature(browser_fetch)
    assert signature.parameters["drain_offer_surface"].default is False


def test_edeka_semantic_price_does_not_confuse_unit_price(monkeypatch):
    monkeypatch.setattr(runtime, "app_today", lambda: date(2026, 9, 1))
    html = '''
    <main>
      <p>Gültig ab 31.08.2026 bis 05.09.2026</p>
      <article data-offer-id="butter-1">
        <h2>Marken Butter 500 g</h2>
        <span class="regular-price">statt 3,49 €</span>
        <span class="offer-price">2,49 €</span>
        <span class="base-price">1 kg = 4,98 €</span>
        <img src="https://offer-images.api.edeka/butter.webp" alt="Marken Butter">
      </article>
    </main>
    '''
    store = _store()
    store.id = 7
    rows = runtime.ReviewedEdekaWebOfferAdapter().parse(html, store, store.source_url, "current")
    assert len(rows) == 1
    assert rows[0].price == 2.49
    assert rows[0].old_price == 3.49
    assert rows[0].unit_price == 4.98


def test_ranked_dedup_keeps_more_complete_offer_over_image_only_variant():
    first = WebOfferRecord(
        "PENNY", 1, "https://www.penny.de/angebote", "Cola", external_offer_id="same",
        price=1.29, quantity="1,5 l", quantity_value=1.5, quantity_unit="l",
        valid_from=date(2026, 8, 31), valid_to=date(2026, 9, 5),
    )
    second = WebOfferRecord(
        "PENNY", 1, "https://www.penny.de/angebote", "Cola", external_offer_id="same",
        price=1.29, image_url="https://img.penny.de/cola.webp",
    )
    rows, duplicates = runtime.quality_deduplicate([first, second])
    assert duplicates == 1
    assert rows[0].quantity_value == 1.5
    assert rows[0].image_url is None
