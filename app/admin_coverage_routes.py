from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_routes import _admin
from .admin_collector_routes import _run_store_collection_background
from .coverage_models import CoveragePostalCode, CoverageRegion, StoreDiscoveryCandidate
from .coverage_service import coverage_payload, region_center, stores_in_region, upsert_discovered_stores
from .db import get_db
from .market_activation import (
    activation_overview,
    assess_latest_store_quality,
    begin_test_scrape,
    publish_store,
    reactivate_store,
    suspend_store,
)
from .models import CollectionRun, Store
from .postcode_coverage_service import (
    candidate_ready_for_promotion,
    promote_candidate_to_store,
    set_postcode_enabled,
    stage_postcode_candidates,
    verify_staged_candidate,
)
from .postcode_geometry import OSM_ATTRIBUTION, OSM_LICENSE_URL, import_postcode_geometry, postcode_feature
from .postcode_reconciliation import deduplicate_candidates, reconcile_postcode_coverage
from .retailer_store_sources import stage_official_store_candidates
from .web_collector import collect_store_from_web

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()

GERMANY_POSTCODE_GEOJSON_URL = (
    "https://raw.githubusercontent.com/tdudek/de-plz-geojson/master/plz-5stellig.geojson"
)
_germany_postcode_geojson_cache: dict | None = None


def safe_external_url(value: str | None) -> str | None:
    """Return an absolute HTTP(S) URL, rejecting unsafe or malformed schemes."""
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned or any(character.isspace() or ord(character) < 32 for character in cleaned):
        return None
    try:
        parsed = urlsplit(cleaned)
        parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    return cleaned


def _load_germany_postcode_geojson() -> dict:
    global _germany_postcode_geojson_cache
    if _germany_postcode_geojson_cache is not None:
        return _germany_postcode_geojson_cache

    response = httpx.get(
        GERMANY_POSTCODE_GEOJSON_URL,
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Spareno-Admin/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("Ungültiger Deutschland-PLZ-Datensatz")
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Deutschland-PLZ-Datensatz enthält keine Flächen")
    _germany_postcode_geojson_cache = payload
    return payload


@router.get("/admin/coverage/postcodes/germany-geojson")
def germany_postcode_geojson(actor: str = Depends(_admin)):
    try:
        payload = _load_germany_postcode_geojson()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, f"Deutschland-PLZ-Layer nicht verfügbar: {type(exc).__name__}") from exc
    return JSONResponse(
        payload,
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Spareno-Geo-Source": "tdudek/de-plz-geojson",
        },
    )


@router.get("/admin/coverage")
def coverage_admin(request: Request, result: str = "", db: Session = Depends(get_db), actor: str = Depends(_admin)):
    regions = db.query(CoverageRegion).order_by(CoverageRegion.created_at.desc()).all()
    payloads = {region.id: coverage_payload(db, region) for region in regions}
    stores = {region.id: stores_in_region(db, region) for region in regions}
    postcodes = db.query(CoveragePostalCode).order_by(CoveragePostalCode.postal_code).all()
    candidates = db.query(StoreDiscoveryCandidate).order_by(
        StoreDiscoveryCandidate.postal_code,
        StoreDiscoveryCandidate.retailer,
        StoreDiscoveryCandidate.name,
    ).all()
    raw_candidates_by_postcode: dict[str, list[StoreDiscoveryCandidate]] = {}
    for candidate in candidates:
        raw_candidates_by_postcode.setdefault(candidate.postal_code, []).append(candidate)
    candidates_by_postcode = {
        postal_code: deduplicate_candidates(rows)
        for postal_code, rows in raw_candidates_by_postcode.items()
    }
    postcode_values = [postcode.postal_code for postcode in postcodes]
    postcode_stores = (
        db.query(Store)
        .filter(Store.postal_code.in_(postcode_values))
        .order_by(Store.postal_code, Store.retailer, Store.name)
        .all()
        if postcode_values
        else []
    )
    stores_by_postcode: dict[str, list[Store]] = {}
    for store in postcode_stores:
        stores_by_postcode.setdefault(store.postal_code, []).append(store)
    activation_overviews = {
        store.id: activation_overview(db, store)
        for store in postcode_stores
    }
    safe_candidate_source_urls = {
        candidate.id: safe_external_url(candidate.source_url)
        for candidate in candidates
    }
    summaries = {
        postcode.postal_code: reconcile_postcode_coverage(db, postcode)
        for postcode in postcodes
    }
    features = []
    for postcode in postcodes:
        summary = summaries[postcode.postal_code]
        feature = postcode_feature(postcode, summary.as_dict())
        if feature:
            features.append(feature)
    return templates.TemplateResponse("admin_coverage.html", {
        "request": request,
        "actor": actor,
        "regions": regions,
        "payloads": payloads,
        "stores": stores,
        "postcodes": postcodes,
        "candidates_by_postcode": candidates_by_postcode,
        "stores_by_postcode": stores_by_postcode,
        "activation_overviews": activation_overviews,
        "safe_candidate_source_urls": safe_candidate_source_urls,
        "coverage_summaries": summaries,
        "postcode_geojson": {"type": "FeatureCollection", "features": features},
        "osm_attribution": OSM_ATTRIBUTION,
        "osm_license_url": OSM_LICENSE_URL,
        "candidate_ready_for_promotion": candidate_ready_for_promotion,
        "result": result,
    })


@router.post("/admin/coverage/postcodes/import")
def import_postcode(
    postal_code: str = Form(...),
    enabled: str = Form("0"),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    try:
        row = import_postcode_geometry(db, postal_code, enabled=enabled == "1")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        db.rollback()
        return RedirectResponse(
            f"/admin/coverage?result=postcode-geometry:{postal_code}:failed={type(exc).__name__}",
            status_code=303,
        )
    return RedirectResponse(
        f"/admin/coverage?result=postcode-geometry:{row.postal_code}:imported",
        status_code=303,
    )


@router.post("/admin/coverage/postcodes/{postal_code}/geometry")
def refresh_postcode_geometry(
    postal_code: str,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    existing = db.query(CoveragePostalCode).filter_by(postal_code=postal_code).first()
    if existing is None:
        raise HTTPException(404, "PLZ nicht gefunden")
    try:
        import_postcode_geometry(db, postal_code)
        result = f"postcode-geometry:{postal_code}:updated"
    except Exception as exc:
        db.rollback()
        result = f"postcode-geometry:{postal_code}:failed={type(exc).__name__}:cache-kept"
    return RedirectResponse(f"/admin/coverage?result={result}", status_code=303)


@router.post("/admin/coverage/postcodes/{postal_code}/toggle")
def toggle_postcode(
    postal_code: str,
    enabled: str = Form("0"),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    try:
        row = set_postcode_enabled(db, postal_code, enabled == "1")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(
        f"/admin/coverage?result=postcode:{row.postal_code}:{'enabled' if row.enabled else 'disabled'}",
        status_code=303,
    )


@router.post("/admin/coverage/postcodes/{postal_code}/discover")
def discover_postcode(postal_code: str, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    postcode = db.query(CoveragePostalCode).filter_by(postal_code=postal_code).first()
    if postcode is None or not postcode.enabled:
        raise HTTPException(400, "PLZ ist nicht freigegeben")
    try:
        official_created, official_updated, _ = stage_official_store_candidates(db, postal_code)
        created, updated = stage_postcode_candidates(db, postal_code)
        result = (
            f"postcode-discover:{postal_code}:osm-new={created}:osm-updated={updated}:"
            f"official-new={official_created}:official-updated={official_updated}"
        )
    except Exception as exc:
        db.rollback()
        result = f"postcode-discover:{postal_code}:failed={type(exc).__name__}"
    return RedirectResponse(f"/admin/coverage?result={result}", status_code=303)


@router.post("/admin/coverage/candidates/{candidate_id}/verify")
def verify_candidate(candidate_id: int, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    try:
        candidate = verify_staged_candidate(db, candidate_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    result = (
        f"candidate:{candidate.id}:address={int(candidate.address_verified)}:"
        f"coords={int(candidate.coordinates_verified)}:official={int(candidate.official_source_verified)}"
    )
    return RedirectResponse(f"/admin/coverage?result={result}", status_code=303)


@router.post("/admin/coverage/candidates/{candidate_id}/official")
def set_candidate_official_verification(
    candidate_id: int,
    verified: str = Form("0"),
    note: str = Form(""),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Marktkandidat nicht gefunden")
    candidate.official_source_verified = verified == "1"
    if note.strip():
        candidate.verification_note = (
            f"{candidate.verification_note}; {note.strip()}" if candidate.verification_note else note.strip()
        )
    candidate.status = "verified" if candidate_ready_for_promotion(candidate) else "discovered"
    candidate.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(f"/admin/coverage?result=candidate:{candidate.id}:official-updated", status_code=303)


@router.post("/admin/coverage/candidates/{candidate_id}/promote")
def promote_candidate(candidate_id: int, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    try:
        store = promote_candidate_to_store(db, candidate_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/admin/coverage?result=candidate:{candidate_id}:store={store.id}", status_code=303)


@router.post("/admin/coverage/stores/{store_id}/test-scrape")
def start_store_test_scrape(
    store_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Markt nicht gefunden")
    running = db.query(CollectionRun).filter_by(store_id=store.id, status="running").first()
    if running:
        return RedirectResponse(
            f"/admin/coverage?result=store:{store.id}:already-running:{running.id}",
            status_code=303,
        )
    try:
        begin_test_scrape(db, store)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    background_tasks.add_task(_run_store_collection_background, store.id, True)
    return RedirectResponse(
        f"/admin/coverage?result=store:{store.id}:test-scrape-started",
        status_code=303,
    )


@router.post("/admin/coverage/stores/{store_id}/quality")
def assess_store_activation_quality(
    store_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Markt nicht gefunden")
    try:
        result = assess_latest_store_quality(db, store)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(
        f"/admin/coverage?result=store:{store.id}:quality:{'passed' if result.passed else 'failed'}",
        status_code=303,
    )


@router.post("/admin/coverage/stores/{store_id}/publish")
def publish_coverage_store(
    store_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Markt nicht gefunden")
    try:
        publish_store(db, store)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/admin/coverage?result=store:{store.id}:public", status_code=303)


@router.post("/admin/coverage/stores/{store_id}/suspend")
def suspend_coverage_store(
    store_id: int,
    reason: str = Form("manuell im Coverage-Admin gesperrt"),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Markt nicht gefunden")
    suspend_store(db, store, reason)
    return RedirectResponse(f"/admin/coverage?result=store:{store.id}:suspended", status_code=303)


@router.post("/admin/coverage/stores/{store_id}/reactivate")
def reactivate_coverage_store(
    store_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Markt nicht gefunden")
    try:
        reactivate_store(db, store)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/admin/coverage?result=store:{store.id}:reactivated", status_code=303)


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
    """Legacy radius onboarding; kept while B2 postcode onboarding is introduced."""
    region = db.get(CoverageRegion, region_id)
    if not region:
        raise HTTPException(404, "Region nicht gefunden")
    created = matched = 0
    try:
        created, matched = upsert_discovered_stores(db, region)
    except Exception:
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
