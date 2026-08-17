from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import FavoriteStore, MasterProduct, Offer, ProductBarcode, ShoppingItem, Store, UserProfile
from app.optimizer import optimize_current_shopping, optimize_shopping
from app.seed import seed_stores
from app.web_collector import _links_from_html, netto_weekly_prospect_url


def _ensure_data():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed_stores(db)
    user = db.query(UserProfile).first()
    if not user:
        user = UserProfile(display_name="Mobile Test", postal_code="57614", city="Steimel", latitude=50.6199, longitude=7.6264, radius_km=50)
        db.add(user)
        db.commit()
        db.refresh(user)
    user.latitude, user.longitude, user.radius_km = 50.6199, 7.6264, 50
    stores = db.query(Store).filter(Store.benchmark_verified.is_(True)).limit(2).all()
    for store in stores:
        if not db.query(FavoriteStore).filter_by(user_id=user.id, store_id=store.id).first():
            db.add(FavoriteStore(user_id=user.id, store_id=store.id))
    product = db.query(MasterProduct).filter_by(normalized_key="mobile-test-product-500g").first()
    if not product:
        product = MasterProduct(name="Mobile Test Produkt", package_size="500 g", normalized_key="mobile-test-product-500g")
        db.add(product)
        db.flush()
    today = date.today()
    for idx, store in enumerate(stores):
        exists = db.query(Offer).filter_by(store_id=store.id, master_product_id=product.id, valid_from=today).first()
        if not exists:
            db.add(Offer(store_id=store.id, master_product_id=product.id, price=2.49 + idx, valid_from=today, valid_to=today + timedelta(days=6), local_store_offer=True))
    db.commit()
    return db, user, product, stores


def test_pdf_link_discovery_prefers_prospect_pdf():
    html = '<a href="/foo">Foo</a><a href="/kw33/wochenprospekt.pdf">Wochenprospekt</a>'
    assert _links_from_html("https://example.test/markt", html)[0] == "https://example.test/kw33/wochenprospekt.pdf"


def test_pdf_link_discovery_finds_flipbook_script_reference():
    html = '<script>window.reader={"pdf":"assets\\/hz34_kess.pdf"};</script>'
    assert _links_from_html("https://wochenprospekt.netto-online.de/hz34_kess/", html)[0] == (
        "https://wochenprospekt.netto-online.de/hz34_kess/assets/hz34_kess.pdf"
    )


def test_netto_weekly_prospect_url_uses_kw_and_official_storeid(monkeypatch):
    db, _, _, _ = _ensure_data()
    store = db.query(Store).filter(Store.name == "Netto Dierdorf").one()
    assert store.external_id == "6822"
    monkeypatch.setattr("app.web_collector.app_today", lambda: date(2026, 8, 17))
    assert netto_weekly_prospect_url(store) == "https://wochenprospekt.netto-online.de/hz34_kess/?storeid=6822"
    db.close()


def test_scanner_can_link_unknown_barcode_and_reopen_product():
    db, _, product, _ = _ensure_data()
    code = "4006381333931"
    old = db.get(ProductBarcode, code)
    if old:
        db.delete(old)
        db.commit()
    product_id = product.id
    db.close()
    client = TestClient(app)
    response = client.post("/scanner/zuordnen", data={"barcode": code, "product_id": product_id}, follow_redirects=True)
    assert response.status_code == 200
    assert "Mobile Test Produkt" in response.text


def test_products_data_status_and_saving_plan_render():
    db, user, product, _ = _ensure_data()
    item = db.query(ShoppingItem).filter_by(user_id=user.id, master_product_id=product.id).first()
    if not item:
        db.add(ShoppingItem(user_id=user.id, master_product_id=product.id, quantity=2))
        db.commit()
    db.close()
    client = TestClient(app)
    for path in ["/produkte?q=Mobile", "/datenstatus", "/sparplan", "/sparplan?view=next"]:
        r = client.get(path)
        assert r.status_code == 200
    current = client.get("/sparplan")
    assert "von" in current.text and "Artikeln im Angebot" in current.text
    upcoming = client.get("/sparplan?view=next")
    assert "Demnächst" in upcoming.text


def test_optimizer_returns_travel_and_single_store_comparison():
    db, user, product, _ = _ensure_data()
    item = db.query(ShoppingItem).filter_by(user_id=user.id, master_product_id=product.id).first()
    if not item:
        item = ShoppingItem(user_id=user.id, master_product_id=product.id, quantity=1)
        db.add(item)
        db.commit()
    result = optimize_current_shopping(db, user, [item])
    assert result.merchandise_total > 0
    assert result.total_with_travel >= result.merchandise_total
    assert result.single_store_total is not None
    assert result.period == "current"
    assert result.total_items == 1
    assert result.offered_items == 1
    db.close()


def test_optimizer_supports_next_period_without_breaking_current_wrapper():
    db, user, product, stores = _ensure_data()
    item = db.query(ShoppingItem).filter_by(user_id=user.id, master_product_id=product.id).first()
    if not item:
        item = ShoppingItem(user_id=user.id, master_product_id=product.id, quantity=1)
        db.add(item)
        db.flush()
    today = date.today()
    next_start = today + timedelta(days=7)
    next_end = next_start + timedelta(days=6)
    existing = db.query(Offer).filter_by(store_id=stores[0].id, master_product_id=product.id, valid_from=next_start).first()
    if not existing:
        db.add(Offer(store_id=stores[0].id, master_product_id=product.id, price=1.99, valid_from=next_start, valid_to=next_end, local_store_offer=True))
    db.commit()
    result = optimize_shopping(db, user, [item], "next")
    assert result.period == "next"
    assert result.merchandise_total >= 0
    assert result.total_items == 1
    assert result.offered_items in {0, 1}
    db.close()
