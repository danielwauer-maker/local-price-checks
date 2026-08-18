from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_routes import _admin
from .coverage_models import CoverageRegion
from .coverage_service import coverage_payload, region_center, stores_in_region, upsert_discovered_stores
from .db import get_db
from .web_collector import collect_store_from_web

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/coverage")
def coverage_admin(request: Request, result: str = "", db: Session = Depends(get_db), actor: str = Depends(_admin)):
    regions = db.query(CoverageRegion).order_by(CoverageRegion.created_at.desc()).all()
    payloads = {region.id: coverage_payload(db, region) for region in regions}
    stores = {region.id: stores_in_region(db, region) for region in regions}
    return templates.TemplateResponse("admin_coverage.html", {
        "request": request,
        "actor": actor,
        "regions": regions,
        "payloads": payloads,
        "stores": stores,
        "result": result,
    })


@router.post("/admin/coverage")
def create_region(
    name: str = Form(...),
    postal_code: str = Form(...),
    city: str = Form(...),
    radius_km: float = Form(15),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    try:
        lat, lng = region_center(postal_code, city)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if db.query(CoverageRegion).filter(CoverageRegion.name == name.strip()).first():
        raise HTTPException(400, "Region mit diesem Namen existiert bereits")
    row = CoverageRegion(
        name=name.strip(), postal_code=postal_code.strip(), city=city.strip(),
        center_lat=lat, center_lng=lng, radius_km=max(2.0, min(float(radius_km), 50.0)),
        status="building", active=True, notes=notes.strip() or None,
    )
    db.add(row)
    db.commit()
    return RedirectResponse(f"/admin/coverage?result=region:{row.id}:created", status_code=303)


@router.post("/admin/coverage/{region_id}/discover")
def discover_region(region_id: int, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    region = db.get(CoverageRegion, region_id)
    if not region:
        raise HTTPException(404, "Region nicht gefunden")
    try:
        created, matched = upsert_discovered_stores(db, region)
        result = f"discover:{region.id}:new={created}:matched={matched}"
    except Exception as exc:
        result = f"discover:{region.id}:failed={type(exc).__name__}"
    return RedirectResponse(f"/admin/coverage?result={result}", status_code=303)


@router.post("/admin/coverage/{region_id}/onboard")
def onboard_region(region_id: int, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    """Discover stores, then run QA collection for every active market in the region."""
    region = db.get(CoverageRegion, region_id)
    if not region:
        raise HTTPException(404, "Region nicht gefunden")
    created = matched = 0
    try:
        created, matched = upsert_discovered_stores(db, region)
    except Exception:
        # Existing stores can still be tested even when Overpass is temporarily unavailable.
        db.rollback()
    ok = failed = 0
    for store in stores_in_region(db, region):
        if not store.active:
            continue
        try:
            collect_store_from_web(db, store.name)
            ok += 1
        except Exception:
            db.rollback()
            failed += 1
    result = f"onboard:{region.id}:new={created}:matched={matched}:scraped={ok}:failed={failed}"
    return RedirectResponse(f"/admin/coverage?result={result}", status_code=303)


@router.post("/admin/coverage/{region_id}/status")
def set_region_status(
    region_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    region = db.get(CoverageRegion, region_id)
    if not region:
        raise HTTPException(404, "Region nicht gefunden")
    if status not in {"building", "live", "paused"}:
        raise HTTPException(400, "Ungültiger Status")
    region.status = status
    region.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(f"/admin/coverage?result=region:{region.id}:{status}", status_code=303)
