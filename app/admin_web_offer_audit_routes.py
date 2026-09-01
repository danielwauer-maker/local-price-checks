from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import _admin
from .db import get_db
from .models import Store
from .web_offer_audit import SUPPORTED_RETAILERS, collector_enabled
from .web_offer_audit_runtime import run_web_offer_audit
from .web_offer_audit_models import WebOfferAuditRun


BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


def _positive_int(value: str | int | None) -> int | None:
    try:
        parsed = int(value) if value not in (None, "") else 0
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _audit_source_url(store: Store) -> str | None:
    """Resolve the admin audit URL without changing the persisted Store source.

    EDEKA exposes a server-rendered central offers surface that accepts the
    selected market id as an explicit query parameter.  This is preferable for
    audits because the market-specific ``/maerkte/<id>/angebote/`` route is
    blocked by EDEKA's CDN for some datacenter/browser traffic.  Other retailers
    continue to use their persisted reviewed source URL.
    """
    if store.retailer == "EDEKA" and store.external_id:
        market_id = "".join(character for character in str(store.external_id).strip() if character.isdigit())
        if market_id:
            return f"https://www.edeka.de/angebote/?selectedMarktID={market_id}"
    return store.source_url


@router.get("/admin/web-offer-audit")
def web_offer_audit_page(
    request: Request,
    store_id: str | None = None,
    run_id: str | None = None,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    stores = (
        db.query(Store)
        .filter(Store.active.is_(True), Store.retailer.in_(SUPPORTED_RETAILERS))
        .order_by(Store.retailer, Store.city, Store.name)
        .all()
    )
    selected_store = db.get(Store, _positive_int(store_id)) if _positive_int(store_id) else (stores[0] if stores else None)
    if selected_store and selected_store.retailer not in SUPPORTED_RETAILERS:
        selected_store = None
    runs = (
        db.query(WebOfferAuditRun)
        .filter(WebOfferAuditRun.store_id == selected_store.id)
        .order_by(WebOfferAuditRun.started_at.desc())
        .limit(20)
        .all()
        if selected_store else []
    )
    selected_run = db.get(WebOfferAuditRun, _positive_int(run_id)) if _positive_int(run_id) else (runs[0] if runs else None)
    if selected_run and (not selected_store or selected_run.store_id != selected_store.id):
        selected_run = None
    comparison = {}
    if selected_run and selected_run.comparison_json:
        try:
            comparison = json.loads(selected_run.comparison_json)
        except json.JSONDecodeError:
            comparison = {}
    return templates.TemplateResponse("admin_web_offer_audit.html", {
        "request": request,
        "actor": actor,
        "stores": stores,
        "selected_store": selected_store,
        "runs": runs,
        "selected_run": selected_run,
        "comparison": comparison,
        "production_enabled": collector_enabled(selected_store.retailer) if selected_store else False,
    })


@router.post("/admin/web-offer-audit/run")
def start_web_offer_audit(
    store_id: int = Form(...),
    period_key: str = Form("current"),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    if period_key not in {"current", "next"}:
        raise HTTPException(status_code=400, detail="Ungültiger Angebotszeitraum")
    store = db.get(Store, store_id)
    if not store or not store.active or store.retailer not in SUPPORTED_RETAILERS:
        raise HTTPException(status_code=404, detail="Unterstützter aktiver Markt nicht gefunden")
    # Only an admin-reviewed Store and a deterministic retailer URL derived
    # from its verified external id can reach the fetcher. The form cannot turn
    # this endpoint into an arbitrary URL fetcher or external redirect.
    try:
        run = run_web_offer_audit(db, store, period_key=period_key, source_url=_audit_source_url(store))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(
        db, "web_offer_audit_run", "web_offer_audit", run.id,
        f"store={store.id}; retailer={store.retailer}; period={period_key}; status={run.status}; count={run.valid_count}", actor,
    )
    db.commit()
    return RedirectResponse(f"/admin/web-offer-audit?store_id={store.id}&run_id={run.id}", status_code=303)
