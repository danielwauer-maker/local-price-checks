from __future__ import annotations

import json
import threading
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from .admin_learning import audit
from .admin_reset import reset_all_test_data, reset_store_offers, reset_store_qa
from .admin_routes import _admin
from .config import settings
from .db import SessionLocal, get_db
from .edeka_discovery import collect_edeka_market_pdf
from .models import CollectionRun, CollectionRunProgress, Store
from .prospects import current_prospect, save_manual_prospect
from .scheduler import run_verified_market_collection
from .support_export import build_support_export
from .collection_quality import BenchmarkContext, CollectionQualitySnapshot
from .web_collector import collect_store_from_web

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()

_LIDL_HARD_TIMEOUT_SECONDS = 550.0


def _expire_stuck_lidl_run(store_id: int) -> None:
    """Close the run even if a browser/native dependency stops responding."""
    db = SessionLocal()
    try:
        run = (
            db.query(CollectionRun)
            .filter(CollectionRun.store_id == store_id, CollectionRun.status == "running")
            .order_by(CollectionRun.started_at.desc())
            .first()
        )
        if run is None:
            return
        progress = (
            db.query(CollectionRunProgress)
            .filter(CollectionRunProgress.run_id == run.id)
            .first()
        )
        phase = progress.phase if progress else "unknown"
        elapsed = progress.elapsed_seconds if progress else _LIDL_HARD_TIMEOUT_SECONDS
        if progress:
            progress.error_type = "timeout"
            progress.updated_at = datetime.utcnow()
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.message = (
            f"run_status=failed error_type=timeout phase={phase} "
            f"elapsed_seconds={max(elapsed, _LIDL_HARD_TIMEOUT_SECONDS):.1f}"
        )
        db.commit()
    finally:
        db.close()


def _write_lidl_debug_failure(store: Store, exc: Exception) -> None:
    """Always persist a Lidl diagnostic record, even if capture setup fails."""
    try:
        target_dir = settings.data_dir / "diagnostics" / "lidl"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"lidl_manifest_debug_store_{store.id}_latest.json"
        target.write_text(
            json.dumps(
                {
                    "created_utc": datetime.utcnow().isoformat() + "Z",
                    "store": {
                        "id": store.id,
                        "name": store.name,
                        "retailer": store.retailer,
                        "external_id": store.external_id,
                    },
                    "leaflet": None,
                    "viewer": {"states": 0, "total": None, "navigation": []},
                    "payload_count": 0,
                    "payloads": [],
                    "error": f"{type(exc).__name__}: {exc}",
                    "stage": "diagnostic_setup",
                    "note": "Fallback diagnostic written because Lidl manifest capture failed before its own output file was created.",
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _persist_background_failure(
    db: Session,
    *,
    store_id: int,
    job_started_at: datetime,
    exc: Exception,
) -> None:
    """Make admin collection failures visible even before a collector run exists."""
    db.rollback()
    run = (
        db.query(CollectionRun)
        .filter(
            CollectionRun.store_id == store_id,
            CollectionRun.started_at >= job_started_at,
        )
        .order_by(CollectionRun.started_at.desc())
        .first()
    )
    now = datetime.utcnow()
    error_type = type(exc).__name__
    error_text = str(exc).strip() or error_type
    message = (
        f"run_status=failed phase=preflight error_type={error_type} "
        f"error={error_text}"
    )[:1800]

    if run is None:
        store = db.get(Store, store_id)
        if store is None:
            return
        run = CollectionRun(
            store_id=store_id,
            source_key=f"admin-preflight:{store.retailer}"[:80],
            started_at=job_started_at,
            finished_at=now,
            status="failed",
            offers_received=0,
            offers_imported=0,
            message=message,
        )
        db.add(run)
        db.flush()
    elif run.status == "running":
        run.status = "failed"
        run.finished_at = now
        run.message = f"{run.message} | {message}"[:1800] if run.message else message
    else:
        return

    progress = (
        db.query(CollectionRunProgress)
        .filter(CollectionRunProgress.run_id == run.id)
        .first()
    )
    if progress is None:
        progress = CollectionRunProgress(
            run_id=run.id,
            phase="preflight",
            error_type=error_type,
            elapsed_seconds=max(0.0, (now - job_started_at).total_seconds()),
            updated_at=now,
        )
        db.add(progress)
    else:
        progress.phase = progress.phase or "preflight"
        progress.error_type = error_type
        progress.elapsed_seconds = max(
            progress.elapsed_seconds or 0.0,
            (now - job_started_at).total_seconds(),
        )
        progress.updated_at = now
    db.commit()


def _run_store_collection_background(store_id: int) -> None:
    """Run one market collection outside the HTTP request lifecycle.

    Long-running browser collectors (especially Lidl flipbooks) can exceed
    nginx's upstream timeout. The background job therefore owns its own DB
    session and continues independently after the admin request has returned.
    """
    db = SessionLocal()
    timeout_timer = None
    job_started_at = datetime.utcnow()
    try:
        store = db.get(Store, store_id)
        if not store or not store.active:
            return
        if store.retailer == "Lidl":
            timeout_timer = threading.Timer(
                _LIDL_HARD_TIMEOUT_SECONDS,
                _expire_stuck_lidl_run,
                args=(store.id,),
            )
            timeout_timer.daemon = True
            timeout_timer.start()
        context = BenchmarkContext.PRODUCTION if store.benchmark_verified else BenchmarkContext.NOT_APPLICABLE
        if store.retailer == "EDEKA":
            collect_edeka_market_pdf(db, store, benchmark_context=context)
        else:
            collect_store_from_web(db, store.name, benchmark_context=context)
    except Exception as exc:
        try:
            _persist_background_failure(
                db,
                store_id=store_id,
                job_started_at=job_started_at,
                exc=exc,
            )
        except Exception:
            db.rollback()
    finally:
        if timeout_timer is not None:
            timeout_timer.cancel()
        db.close()


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
    run_ids = {run.id for run in recent}
    run_ids.update(run.id for run in latest.values() if run is not None)
    quality_by_run = {
        snapshot.run_id: snapshot
        for snapshot in (
            db.query(CollectionQualitySnapshot)
            .filter(CollectionQualitySnapshot.run_id.in_(run_ids))
            .all()
            if run_ids
            else []
        )
    }
    progress_by_run = {
        progress.run_id: progress
        for progress in (
            db.query(CollectionRunProgress)
            .filter(CollectionRunProgress.run_id.in_(run_ids))
            .all()
            if run_ids
            else []
        )
    }
    return templates.TemplateResponse("admin_collector.html", {
        "request": request, "actor": actor, "stores": stores, "latest": latest,
        "prospects": prospects, "next_prospects": next_prospects, "recent": recent,
        "collected": collected, "scheduler_enabled": settings.scheduler_enabled,
        "manual_collection_enabled": settings.manual_collection_enabled,
        "quality_by_run": quality_by_run,
        "progress_by_run": progress_by_run,
    })


@router.post("/admin/collector/run-all")
def collector_run_all(actor: str = Depends(_admin)):
    results = run_verified_market_collection()
    ok = sum(1 for value in results.values() if not value.startswith("failed:"))
    return RedirectResponse(f"/admin/collector?collected=all:{ok}/{len(results)}", status_code=303)


@router.post("/admin/collector/stores/{store_id}/run")
def collector_run_store(
    store_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Markt nicht gefunden")
    if not store.active:
        raise HTTPException(400, "Inaktive Märkte können nicht gesammelt werden")

    running = (
        db.query(CollectionRun)
        .filter(CollectionRun.store_id == store.id, CollectionRun.status == "running")
        .order_by(CollectionRun.started_at.desc())
        .first()
    )
    if running:
        return RedirectResponse(
            f"/admin/collector?collected={store.id}:already-running:{running.id}",
            status_code=303,
        )

    background_tasks.add_task(_run_store_collection_background, store.id)
    mode = "live" if store.benchmark_verified else "qa"
    return RedirectResponse(
        f"/admin/collector?collected={store.id}:{mode}:gestartet",
        status_code=303,
    )


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


@router.post("/admin/collector/stores/{store_id}/reset-offers")
def collector_reset_store_offers(
    store_id: int,
    confirm: str = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Markt nicht gefunden")
    if confirm != "RESET":
        raise HTTPException(400, "Bestätigung für Angebotsreset fehlt")
    result = reset_store_offers(db, store)
    audit(db, "store_offer_reset", "store", store.id, str(result), actor)
    db.commit()
    return RedirectResponse(
        f"/admin/collector?collected=reset-angebote:{store.id}:{result['offers']}angebote:{result['orphan_products']}artikel",
        status_code=303,
    )


@router.post("/admin/collector/stores/{store_id}/reset-qa")
def collector_reset_store_qa(
    store_id: int,
    confirm: str = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Markt nicht gefunden")
    if confirm != "RESET QA":
        raise HTTPException(400, "Bestätigung für QA-Reset fehlt")
    result = reset_store_qa(db, store)
    audit(db, "store_qa_reset", "store", store.id, str(result), actor)
    db.commit()
    return RedirectResponse(
        f"/admin/collector?collected=reset-qa:{store.id}:{result['offers']}angebote:{result['prospects']}prospekte",
        status_code=303,
    )


@router.post("/admin/collector/reset-all-test-data")
def collector_reset_all_test_data(
    confirm: str = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    if confirm.strip() != "ALLES ZURUECKSETZEN":
        raise HTTPException(400, "Bitte exakt ALLES ZURUECKSETZEN eingeben")
    result = reset_all_test_data(db)
    audit(db, "all_test_data_reset", "system", "catalog", str(result), actor)
    db.commit()
    return RedirectResponse(
        f"/admin/collector?collected=gesamtreset:{result['offers']}angebote:{result['products']}artikel:{result['archives']}prospekte",
        status_code=303,
    )


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
