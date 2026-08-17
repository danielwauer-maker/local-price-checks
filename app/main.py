from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .barcode import normalize_gtin, valid_gtin
from .barcode_image import BarcodeImageError, decode_gtin_image
from .config import settings
from .db import Base, engine, get_db
from .freshness import market_freshness
from .geo import haversine_km, resolve_center
from .models import FavoriteProduct, FavoriteStore, MasterProduct, ProductBarcode, ShoppingItem, Store
from .optimizer import optimize_shopping
from .scheduler import run_verified_market_collection, start_scheduler, stop_scheduler
from .seed import seed_stores
from .services import current_user, offers_for_selected_stores, selected_store_ids

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Local Price Checks", version="0.2.0")
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
    start_scheduler()


@app.on_event("shutdown")
def shutdown():
    stop_scheduler()


@app.get("/health")
def health(db: Session = Depends(get_db)):
    verified = db.query(Store).filter(Store.benchmark_verified.is_(True), Store.active.is_(True)).count()
    freshness = market_freshness(db)
    problems = sum(1 for row in freshness if row["state"] in {"failed", "stale"})
    return {
        "status": "ok" if problems == 0 else "degraded",
        "verified_stores": verified,
        "collection_problems": problems,
        "scheduler_enabled": settings.scheduler_enabled,
        "date": date.today().isoformat(),
    }


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(db)
    favorite_rows = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id).all()
    favorite_ids = {row.master_product_id for row in favorite_rows}
    current = [o for o in offers_for_selected_stores(db, user, "current") if o.master_product_id in favorite_ids]
    upcoming = [o for o in offers_for_selected_stores(db, user, "next") if o.master_product_id in favorite_ids]
    shopping_items = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    selected = len(selected_store_ids(db, user))
    home_plan = optimize_shopping(db, user, shopping_items, "current")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "current": current[:6],
            "upcoming": upcoming[:6],
            "favorites": len(favorite_rows),
            "shopping": len(shopping_items),
            "selected": selected,
            "home_plan": home_plan,
        },
    )


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


@app.get("/produkte")
def products_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    user = current_user(db)
    query = db.query(MasterProduct)
    if q.strip():
        query = query.filter(MasterProduct.name.ilike(f"%{q.strip()}%"))
    products = query.order_by(MasterProduct.name).limit(100).all()
    fav_ids = {x.master_product_id for x in db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id).all()}

    current_by_product = {}
    for offer in offers_for_selected_stores(db, user, "current"):
        previous = current_by_product.get(offer.master_product_id)
        if previous is None or offer.price < previous.price:
            current_by_product[offer.master_product_id] = offer

    upcoming_by_product = {}
    for offer in offers_for_selected_stores(db, user, "next"):
        previous = upcoming_by_product.get(offer.master_product_id)
        if previous is None or offer.price < previous.price:
            upcoming_by_product[offer.master_product_id] = offer

    return templates.TemplateResponse(
        "products.html",
        {
            "request": request,
            "products": products,
            "q": q,
            "fav_ids": fav_ids,
            "current": current_by_product,
            "upcoming": upcoming_by_product,
        },
    )


@app.post("/favoriten/{product_id}/toggle")
def toggle_product_favorite(product_id: int, next_url: str = Form("/favoriten"), db: Session = Depends(get_db)):
    user = current_user(db)
    product = db.get(MasterProduct, product_id)
    if product:
        existing = db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user.id, FavoriteProduct.master_product_id == product_id).first()
        if existing:
            db.delete(existing)
        else:
            db.add(FavoriteProduct(user_id=user.id, master_product_id=product_id))
        db.commit()
    return RedirectResponse(next_url if next_url.startswith("/") else "/favoriten", status_code=303)


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
def shopping_page(
    request: Request,
    q: str = "",
    max_stores: int = 2,
    db: Session = Depends(get_db),
):
    user = current_user(db)
    rows = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    max_stores = max(1, min(max_stores, 3))
    plan = optimize_shopping(db, user, rows, "current", max_stores=max_stores)

    suggestions = []
    if q.strip():
        term = f"%{q.strip()}%"
        suggestions = (
            db.query(MasterProduct)
            .filter((MasterProduct.name.ilike(term)) | (MasterProduct.brand.ilike(term)))
            .order_by(MasterProduct.name)
            .limit(8)
            .all()
        )

    grouped = []
    for store in plan.stores:
        lines = [(item, offer) for item, offer in plan.picks if offer and offer.store_id == store.id]
        subtotal = sum(offer.price * item.quantity for item, offer in lines)
        grouped.append({"store": store, "lines": lines, "subtotal": subtotal})
    missing = [item for item, offer in plan.picks if offer is None]

    return templates.TemplateResponse(
        "shopping.html",
        {
            "request": request,
            "rows": rows,
            "q": q,
            "suggestions": suggestions,
            "selected_count": len(selected_store_ids(db, user)),
            "plan": plan,
            "grouped": grouped,
            "missing": missing,
            "max_stores": max_stores,
        },
    )


@app.post("/einkauf/{product_id}/add")
def add_shopping(product_id: int, next_url: str = Form("/einkauf"), db: Session = Depends(get_db)):
    user = current_user(db)
    item = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id, ShoppingItem.master_product_id == product_id).first()
    if item:
        item.quantity += 1
    elif db.get(MasterProduct, product_id):
        db.add(ShoppingItem(user_id=user.id, master_product_id=product_id, quantity=1))
    db.commit()
    target = next_url if next_url.startswith("/") else "/einkauf"
    return RedirectResponse(target, status_code=303)


@app.post("/einkauf/{item_id}/update")
def update_shopping(item_id: int, quantity: float = Form(...), next_url: str = Form("/einkauf"), db: Session = Depends(get_db)):
    user = current_user(db)
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id, ShoppingItem.user_id == user.id).first()
    if item:
        if quantity <= 0:
            db.delete(item)
        else:
            item.quantity = min(quantity, 999)
        db.commit()
    target = next_url if next_url.startswith("/") else "/einkauf"
    return RedirectResponse(target, status_code=303)


@app.post("/einkauf/{item_id}/delete")
def delete_shopping(item_id: int, db: Session = Depends(get_db)):
    user = current_user(db)
    item = db.query(ShoppingItem).filter(ShoppingItem.id == item_id, ShoppingItem.user_id == user.id).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse("/einkauf", status_code=303)


@app.post("/einkauf/clear")
def clear_shopping(db: Session = Depends(get_db)):
    user = current_user(db)
    db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).delete()
    db.commit()
    return RedirectResponse("/einkauf", status_code=303)


@app.get("/angebote")
def offers_page(
    request: Request,
    view: str = "current",
    q: str = "",
    retailer: str = "",
    db: Session = Depends(get_db),
):
    user = current_user(db)
    period = "next" if view == "next" else "current"
    offers = offers_for_selected_stores(db, user, period)
    retailers = sorted({o.store.retailer for o in offers if o.store and o.store.retailer})
    if q.strip():
        needle = q.strip().lower()
        offers = [
            o for o in offers
            if needle in (o.product.name or "").lower() or needle in (o.product.brand or "").lower()
        ]
    if retailer.strip():
        offers = [o for o in offers if (o.store.retailer or "").lower() == retailer.strip().lower()]
    return templates.TemplateResponse(
        "offers.html",
        {
            "request": request,
            "offers": offers,
            "view": period,
            "q": q,
            "retailer": retailer,
            "retailers": retailers,
            "selected_count": len(selected_store_ids(db, user)),
        },
    )


@app.get("/scanner")
def scanner_page(request: Request, barcode: str = "", db: Session = Depends(get_db)):
    code = normalize_gtin(barcode)
    result = None
    error = None
    if code:
        if not valid_gtin(code):
            error = "Ungültige GTIN/EAN-Prüfziffer."
        else:
            row = db.get(ProductBarcode, code)
            result = row.master_product if row else None
    return templates.TemplateResponse("scanner.html", {"request": request, "result": result, "barcode": code, "error": error})


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


@app.post("/scanner/bild")
async def scanner_image(request: Request, image: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        code = decode_gtin_image(await image.read())
    except BarcodeImageError as exc:
        return templates.TemplateResponse("scanner.html", {"request": request, "result": None, "barcode": "", "error": str(exc)})
    if not code:
        return templates.TemplateResponse("scanner.html", {"request": request, "result": None, "barcode": "", "error": "Auf dem Foto wurde keine gültige EAN/GTIN erkannt. Bitte näher und schärfer fotografieren."})
    row = db.get(ProductBarcode, code)
    result = row.master_product if row else None
    return templates.TemplateResponse("scanner.html", {"request": request, "result": result, "barcode": code, "error": None})


@app.post("/scanner/suche")
def scanner_search(request: Request, barcode: str = Form(...), q: str = Form(...), db: Session = Depends(get_db)):
    code = normalize_gtin(barcode)
    if not valid_gtin(code):
        return templates.TemplateResponse("scanner.html", {"request": request, "barcode": code, "error": "Ungültige GTIN/EAN-Prüfziffer.", "result": None})
    candidates = db.query(MasterProduct).filter(MasterProduct.name.ilike(f"%{q.strip()}%")).limit(30).all() if q.strip() else []
    return templates.TemplateResponse("scanner.html", {"request": request, "result": None, "barcode": code, "q": q, "candidates": candidates})


@app.post("/scanner/zuordnen")
def scanner_link(barcode: str = Form(...), product_id: int = Form(...), db: Session = Depends(get_db)):
    code = normalize_gtin(barcode)
    product = db.get(MasterProduct, product_id)
    if valid_gtin(code) and product:
        row = db.get(ProductBarcode, code)
        if row:
            row.master_product_id = product.id
        else:
            db.add(ProductBarcode(barcode=code, master_product_id=product.id, source="user"))
        db.commit()
    return RedirectResponse(f"/scanner?barcode={code}", status_code=303)


@app.get("/datenstatus")
def data_status(request: Request, collected: int = 0, db: Session = Depends(get_db)):
    manual_enabled = settings.manual_collection_enabled or settings.app_env in {"development", "local"}
    return templates.TemplateResponse(
        "data_status.html",
        {
            "request": request,
            "rows": market_freshness(db),
            "scheduler_enabled": settings.scheduler_enabled,
            "manual_collection_enabled": manual_enabled,
            "collection_finished": bool(collected),
        },
    )


@app.post("/datenstatus/sammeln")
def collect_now():
    manual_enabled = settings.manual_collection_enabled or settings.app_env in {"development", "local"}
    if not manual_enabled:
        return RedirectResponse("/datenstatus", status_code=303)
    run_verified_market_collection()
    return RedirectResponse("/datenstatus?collected=1", status_code=303)


@app.get("/sparplan")
def saving_plan(
    request: Request,
    view: str = "current",
    max_stores: int = 3,
    db: Session = Depends(get_db),
):
    user = current_user(db)
    items = db.query(ShoppingItem).filter(ShoppingItem.user_id == user.id).all()
    period = "next" if view == "next" else "current"
    max_stores = max(1, min(max_stores, 3))
    plan = optimize_shopping(db, user, items, period, max_stores=max_stores)
    return templates.TemplateResponse("plan.html", {"request": request, "plan": plan, "view": period, "max_stores": max_stores})
