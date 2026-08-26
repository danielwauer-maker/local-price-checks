from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from .admin_learning import audit
from .admin_routes import _admin
from .db import get_db
from .feature_flags import DEFAULT_FEATURE_FLAGS, get_feature_flags, set_feature_flag
from .models import MasterProduct, Store
from .market_activation import activation_overview, publish_store, suspend_store
from .normal_prices import add_normal_price_observation, backfill_explicit_references

BASE = Path(__file__).resolve().parent
router = APIRouter()
templates = Jinja2Templates(directory=BASE / "templates")


@router.get("/admin/lokero-controls")
def lokero_controls(request: Request, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    flags = get_feature_flags(db)
    stores = db.query(Store).order_by(Store.retailer, Store.city, Store.name).all()
    activation_overviews = {store.id: activation_overview(db, store) for store in stores}
    return templates.TemplateResponse(
        "admin_lokero_controls.html",
        {
            "request": request,
            "actor": actor,
            "flags": flags,
            "defaults": DEFAULT_FEATURE_FLAGS,
            "stores": stores,
            "activation_overviews": activation_overviews,
        },
    )


@router.post("/admin/lokero-controls/feature/{name}")
def update_feature(
    name: str,
    enabled: str = Form("0"),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    try:
        set_feature_flag(db, name, enabled == "1")
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown feature flag")
    audit(db, "lokero_feature_changed", "feature", name, f"enabled={enabled == '1'}", actor)
    db.commit()
    return RedirectResponse("/admin/lokero-controls", status_code=303)


@router.post("/admin/lokero-controls/store/{store_id}/release")
def release_store(
    store_id: int,
    released: str = Form("0"),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    try:
        if released == "1":
            publish_store(db, store)
        else:
            suspend_store(db, store, "manuell in der Produktsteuerung gesperrt")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, "lokero_store_release_changed", "store", store.id, f"released={store.benchmark_verified}", actor)
    db.commit()
    return RedirectResponse("/admin/lokero-controls", status_code=303)


@router.post("/admin/lokero-controls/normal-price")
def save_normal_price(
    product_id: int = Form(...),
    store_id: int = Form(...),
    price: float = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    product = db.get(MasterProduct, product_id)
    store = db.get(Store, store_id)
    if not product or not store or price <= 0:
        raise HTTPException(status_code=400, detail="Invalid product/store/price")
    row = add_normal_price_observation(
        db,
        master_product_id=product.id,
        store_id=store.id,
        retailer=store.retailer,
        price=price,
        source="admin_manual",
        confidence=1.0,
        notes=notes.strip() or None,
    )
    db.flush()
    audit(db, "normal_price_saved", "normal_price", row.id, f"product={product.id};store={store.id};price={price}", actor)
    db.commit()
    return RedirectResponse("/admin/lokero-controls", status_code=303)


@router.post("/admin/lokero-controls/normal-price/backfill")
def backfill_normal_prices(db: Session = Depends(get_db), actor: str = Depends(_admin)):
    created = backfill_explicit_references(db)
    audit(db, "normal_price_backfill", "normal_price", None, f"created={created}", actor)
    db.commit()
    return RedirectResponse(f"/admin/lokero-controls?backfilled={created}", status_code=303)
