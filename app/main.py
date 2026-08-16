from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .barcode import normalize_gtin, valid_gtin
from .db import Base, engine, get_db
from .geo import haversine_km, resolve_center
from .models import FavoriteProduct, FavoriteStore, MasterProduct, ProductBarcode, ShoppingItem, Store
from .seed import seed_stores
from .services import current_user, offers_for_selected_stores, selected_store_ids

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Local Price Checks", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    from .db import SessionLocal
    db = SessionLocal()
    try:
        seed_stores(db)
        current_user(db)
    finally:
        db.close()


@app.get("/health")
def health(db: Session = Depends(get_db)):
    verified = db.query(Store).filter(Store.benchmark_verified.is_(True), Store.active.is_(True)).count()
    return {"status": "ok", "verified_stores": verified, "date": date.today().isoformat()}


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(db)
    current = offers_for_selected_stores(db, user, "current")
    upcoming = offers_for_selected_stores(db, user, "next")
    favorites = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id).count()
    shopping = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).count()
    return templates.TemplateResponse("index.html", {"request": request, "user": user, "current": current[:6], "upcoming": upcoming[:6], "favorites": favorites, "shopping": shopping})


@app.get("/maerkte")
def stores_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(db)
    favorites = {x.store_id for x in db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id).all()}
    stores = db.query(Store).filter(Store.active.is_(True)).order_by(Store.city, Store.name).all()
    rows = []
    for store in stores:
        distance = None
        if None not in (user.latitude, user.longitude, store.latitude, store.longitude):
            distance = haversine_km(user.latitude, user.longitude, store.latitude, store.longitude)
        rows.append((store, distance, store.id in favorites))
    return templates.TemplateResponse("stores.html", {"request": request, "user": user, "rows": rows})


@app.post("/maerkte/standort")
def save_location(postal_code: str = Form(...), city: str = Form(...), radius_km: float = Form(15), db: Session = Depends(get_db)):
    user = current_user(db)
    user.postal_code, user.city, user.radius_km = postal_code.strip(), city.strip(), max(1, min(radius_km, 50))
    center = resolve_center(user.postal_code, user.city)
    if center:
        user.latitude, user.longitude = center
    db.commit()
    return RedirectResponse("/maerkte", status_code=303)


@app.post("/maerkte/{store_id}/toggle")
def toggle_store(store_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    store = db.get(Store, store_id)
    if not store or not store.active or not store.benchmark_verified:
        return RedirectResponse("/maerkte", status_code=303)
    existing = db.query(FavoriteStore).filter(FavoriteStore.user_id == user.id, FavoriteStore.store_id == store_id).first()
    if existing:
        db.delete(existing)
    else:
        db.add(FavoriteStore(user_id=user.id, store_id=store_id))
    db.commit()
    return RedirectResponse("/maerkte", status_code=303)


@app.get("/favoriten")
def favorites_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(db)
    rows = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id).all()
    current = offers_for_selected_stores(db, user, "current")
    upcoming = offers_for_selected_stores(db, user, "next")
    by_current, by_upcoming = {}, {}
    for offer in current:
        by_current.setdefault(offer.master_product_id, offer)
    for offer in upcoming:
        by_upcoming.setdefault(offer.master_product_id, offer)
    return templates.TemplateResponse("favorites.html", {"request": request, "rows": rows, "current": by_current, "upcoming": by_upcoming})


@app.get("/einkauf")
def shopping_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(db)
    rows = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    return templates.TemplateResponse("shopping.html", {"request": request, "rows": rows})


@app.post("/einkauf/{product_id}/add")
def add_shopping(product_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    item = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id, ShoppingItem.master_product_id == product_id).first()
    if item:
        item.quantity += 1
    elif db.get(MasterProduct, product_id):
        db.add(ShoppingItem(user_id=user.id, master_product_id=product_id, quantity=1))
    db.commit()
    return RedirectResponse("/einkauf", status_code=303)


@app.get("/angebote")
def offers_page(request: Request, view: str = "current", db: Session = Depends(get_db)):
    user = current_user(db)
    offers = offers_for_selected_stores(db, user, "next" if view == "next" else "current")
    return templates.TemplateResponse("offers.html", {"request": request, "offers": offers, "view": view})


@app.get("/scanner")
def scanner_page(request: Request):
    return templates.TemplateResponse("scanner.html", {"request": request, "result": None})


@app.post("/scanner")
def scanner_lookup(request: Request, barcode: str = Form(...), db: Session = Depends(get_db)):
    code = normalize_gtin(barcode)
    result = None
    error = None
    if not valid_gtin(code):
        error = "Ungültige GTIN/EAN-Prüfziffer."
    else:
        row = db.get(ProductBarcode, code)
        result = row.master_product if row else None
    return templates.TemplateResponse("scanner.html", {"request": request, "result": result, "barcode": code, "error": error})


@app.get("/sparplan")
def saving_plan(request: Request, db: Session = Depends(get_db)):
    user = current_user(db)
    store_ids = selected_store_ids(db, user)
    items = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    offers = offers_for_selected_stores(db, user, "current")
    by_product = {}
    for offer in offers:
        by_product.setdefault(offer.master_product_id, []).append(offer)
    picks = []
    total = 0.0
    for item in items:
        opts = by_product.get(item.master_product_id, [])
        if not opts:
            picks.append((item, None))
            continue
        best = min(opts, key=lambda x: x.price)
        total += best.price * item.quantity
        picks.append((item, best))
    return templates.TemplateResponse("plan.html", {"request": request, "picks": picks, "total": total, "store_ids": store_ids})
