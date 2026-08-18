from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from .admin_routes import _admin
from .config import settings
from .db import get_db
from .models import CollectionRun, Store
from .prospects import current_prospect, save_manual_prospect
from .scheduler import run_verified_market_collection
from .support_export import build_support_export
from .web_collector import collect_store_from_web

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/collector")
def collector_admin(request: Request, collected: str = "", db: Session = Depends(get_db), actor: str = Depends(_admin)):
    stores = db.query(Store).order_by(Store.retailer, Store.city, Store.name).all()
    latest = {}
    prospects = {}
    next_prospects = {}
    for store in stores:
        run = db.query(CollectionRun).filter(CollectionRun.store_id == store.id).order_by(CollectionRun.started_at.desc()).first()
        latest[store.id] = run
        prospects[store.id] = current_prospect(db, store, "current")
        next_prospects[store.id] = current_prospect(db, store, "next")
    recent = db.query(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(30).all()
    return templates.TemplateResponse("admin_collector.html", {
        "request": request, "actor": actor, "stores": stores, "latest": latest,
        "prospects": prospects, "next_prospects": next_prospects, "recent": recent,
        "collected": collected, "scheduler_enabled": settings.scheduler_enabled,
        "manual_collection_enabled": settings.manual_collection_enabled,
    })


@router.post("/admin/collector/run-all")
def collector_run_all(actor: str = Depends(_admin)):
    results = run_verified_market_collection()
    ok = sum(1 for value in results.values() if not value.startswith("failed:"))
    return RedirectResponse(f"/admin/collector?collected=all:{ok}/{len(results)}", status_code=303)


@router.post("/admin/collector/stores/{store_id}/run")
def collector_run_store(store_id: int, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Markt nicht gefunden")
    if not store.active:
        raise HTTPException(400, "Inaktive Märkte können nicht gesammelt werden")
    try:
        _rows, summary, run = collect_store_from_web(db, store.name)
        mode = "live" if store.benchmark_verified else "qa"
        result = f"{mode}:{run.status}:{summary.imported}"
    except Exception as exc:
        result = f"failed:{type(exc).__name__}"
    return RedirectResponse(f"/admin/collector?collected={store.id}:{result}", status_code=303)


@router.post("/admin/collector/stores/{store_id}/release")
def collector_release_store(
    store_id: int,
    released: str = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Markt nicht gefunden")
    store.benchmark_verified = released == "1"
    db.commit()
    state = "released" if store.benchmark_verified else "qa"
    return RedirectResponse(f"/admin/collector?collected={store.id}:{state}", status_code=303)


@router.post("/admin/collector/stores/{store_id}/prospect-upload")
async def upload_store_prospect(
    store_id: int,
    period: str = Form("current"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Markt nicht gefunden")
    if period not in {"current", "next"}:
        raise HTTPException(400, "Ungültiger Zeitraum")
    payload = await file.read()
    try:
        row = save_manual_prospect(db, store, period_key=period, filename=file.filename or "prospekt.pdf", payload=payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/admin/collector?collected=prospekt:{store.id}:{period}:{row.page_count}seiten", status_code=303)


@router.get("/admin/support-export.zip")
def support_export(db: Session = Depends(get_db), actor: str = Depends(_admin)):
    filename, payload = build_support_export(db)
    return Response(content=payload, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
