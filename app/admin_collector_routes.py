from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi import Request
from sqlalchemy.orm import Session
from pathlib import Path

from .admin_routes import _admin
from .config import settings
from .db import get_db
from .models import CollectionRun, Store
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
    for store in stores:
        run = (
            db.query(CollectionRun)
            .filter(CollectionRun.store_id == store.id)
            .order_by(CollectionRun.started_at.desc())
            .first()
        )
        latest[store.id] = run
    recent = db.query(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(30).all()
    return templates.TemplateResponse(
        "admin_collector.html",
        {
            "request": request,
            "actor": actor,
            "stores": stores,
            "latest": latest,
            "recent": recent,
            "collected": collected,
            "scheduler_enabled": settings.scheduler_enabled,
            "manual_collection_enabled": settings.manual_collection_enabled,
        },
    )


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
    if not store.active or not store.benchmark_verified:
        raise HTTPException(400, "Nur aktive, verifizierte Märkte können automatisch gesammelt werden")
    try:
        _rows, summary, run = collect_store_from_web(db, store.name)
        result = f"{run.status}:{summary.imported}"
    except Exception as exc:
        result = f"failed:{type(exc).__name__}"
    return RedirectResponse(f"/admin/collector?collected={store.id}:{result}", status_code=303)


@router.get("/admin/support-export.zip")
def support_export(db: Session = Depends(get_db), actor: str = Depends(_admin)):
    filename, payload = build_support_export(db)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
