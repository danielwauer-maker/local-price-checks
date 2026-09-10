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
from .edeka_web_offer_audit_orchestrator import run_web_offer_audit
from .models import Store
from .offer_accuracy import build_offer_accuracy_scorecard
from .physical_market_identity import canonical_store_map, collapse_physical_stores
from .web_offer_audit import SUPPORTED_RETAILERS, collector_enabled
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
    """Resolve the admin audit URL without changing the persisted Store source."""
    if store.retailer == "EDEKA" and store.external_id:
        market_id = "".join(character for character in str(store.external_id).strip() if character.isdigit())
        if market_id:
            return f"https://www.edeka.de/maerkte/{market_id}/angebote/"
    return store.source_url


def _active_retailer_rows(db: Session, retailer: str) -> list[Store]:
    return db.query(Store).filter(Store.active.is_(True), Store.retailer == retailer).all()


def _canonical_active_store(db: Session, store: Store) -> Store:
    """Resolve an active Store alias to the preferred physical-market row."""
    rows = _active_retailer_rows(db, store.retailer)
    return canonical_store_map(rows).get(store.id, store)


def _physical_store_ids(db: Session, store: Store) -> tuple[int, ...]:
    """Return every persisted Store row representing the same physical market."""
    rows = db.query(Store).filter(Store.retailer == store.retailer).all()
    mapping = canonical_store_map(rows)
    canonical = mapping.get(store.id, store)
    return tuple(row.id for row in rows if mapping.get(row.id, row).id == canonical.id)


def _resolved_audit_source_url(db: Session, store: Store) -> str | None:
    """Prefer the canonical source, then a source from an alias of the same market."""
    direct = _audit_source_url(store)
    if direct:
        return direct
    for alias_id in _physical_store_ids(db, store):
        alias = db.get(Store, alias_id)
        if alias and alias.id != store.id:
            candidate = _audit_source_url(alias)
            if candidate:
                return candidate
    return None


def _supported_active_stores(db: Session) -> list[Store]:
    raw = (
        db.query(Store)
        .filter(Store.active.is_(True), Store.retailer.in_(SUPPORTED_RETAILERS))
        .all()
    )
    return sorted(
        collapse_physical_stores(raw),
        key=lambda row: (row.retailer, row.city or "", row.name or "", row.id),
    )


def _rewe_beta_market_statuses(db: Session) -> list[dict]:
    """Return one read-only current-week accuracy status per physical REWE market."""
    verified_rows = (
        db.query(Store)
        .filter(
            Store.active.is_(True),
            Store.benchmark_verified.is_(True),
            Store.retailer == "REWE",
        )
        .all()
    )
    mapping = canonical_store_map(verified_rows)
    groups: dict[int, list[Store]] = {}
    canonical_by_id: dict[int, Store] = {}
    for row in verified_rows:
        canonical = mapping[row.id]
        canonical_by_id[canonical.id] = canonical
        groups.setdefault(canonical.id, []).append(row)

    statuses: list[dict] = []
    for canonical_id, members in groups.items():
        store = canonical_by_id[canonical_id]
        member_ids = [row.id for row in members]
        run = (
            db.query(WebOfferAuditRun)
            .filter(
                WebOfferAuditRun.store_id.in_(member_ids),
                WebOfferAuditRun.retailer == "REWE",
                WebOfferAuditRun.period_key == "current",
            )
            .order_by(WebOfferAuditRun.started_at.desc(), WebOfferAuditRun.id.desc())
            .first()
        )
        scorecard = build_offer_accuracy_scorecard(db, run) if run and run.status == "success" else {}
        if not run:
            state = "not_audited"
        elif run.status != "success":
            state = "audit_failed"
        elif scorecard.get("accuracy_beta_ready"):
            state = "beta_ready"
        else:
            state = "needs_review"
        statuses.append({
            "store": store,
            "run": run,
            "scorecard": scorecard,
            "state": state,
            "alias_store_ids": tuple(sorted(member_ids)),
        })

    return sorted(
        statuses,
        key=lambda row: (
            row["store"].postal_code or "",
            row["store"].city or "",
            row["store"].name or "",
            row["store"].id,
        ),
    )


@router.get("/admin/web-offer-audit")
def web_offer_audit_page(
    request: Request,
    store_id: str | None = None,
    run_id: str | None = None,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    stores = _supported_active_stores(db)
    requested_id = _positive_int(store_id)
    requested_store = db.get(Store, requested_id) if requested_id else None
    selected_store = (
        _canonical_active_store(db, requested_store)
        if requested_store and requested_store.active and requested_store.retailer in SUPPORTED_RETAILERS
        else (stores[0] if stores else None)
    )
    alias_ids = _physical_store_ids(db, selected_store) if selected_store else ()
    runs = (
        db.query(WebOfferAuditRun)
        .filter(WebOfferAuditRun.store_id.in_(alias_ids))
        .order_by(WebOfferAuditRun.started_at.desc())
        .limit(20)
        .all()
        if selected_store else []
    )
    selected_run = db.get(WebOfferAuditRun, _positive_int(run_id)) if _positive_int(run_id) else (runs[0] if runs else None)
    if selected_run and (not selected_store or selected_run.store_id not in alias_ids):
        selected_run = None
    comparison = {}
    if selected_run and selected_run.comparison_json:
        try:
            comparison = json.loads(selected_run.comparison_json)
        except json.JSONDecodeError:
            comparison = {}
    if selected_run and selected_run.status == "success":
        comparison.update(build_offer_accuracy_scorecard(db, selected_run))
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


@router.get("/admin/rewe-beta-accuracy")
def rewe_beta_accuracy_page(
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    statuses = _rewe_beta_market_statuses(db)
    return templates.TemplateResponse("admin_rewe_beta_accuracy.html", {
        "request": request,
        "actor": actor,
        "statuses": statuses,
        "ready_count": sum(row["state"] == "beta_ready" for row in statuses),
        "total_count": len(statuses),
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
    requested_store = db.get(Store, store_id)
    if not requested_store or not requested_store.active or requested_store.retailer not in SUPPORTED_RETAILERS:
        raise HTTPException(status_code=404, detail="Unterstützter aktiver Markt nicht gefunden")
    store = _canonical_active_store(db, requested_store)
    try:
        run = run_web_offer_audit(
            db,
            store,
            period_key=period_key,
            source_url=_resolved_audit_source_url(db, store),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(
        db, "web_offer_audit_run", "web_offer_audit", run.id,
        f"store={store.id}; retailer={store.retailer}; period={period_key}; status={run.status}; count={run.valid_count}", actor,
    )
    db.commit()
    return RedirectResponse(f"/admin/web-offer-audit?store_id={store.id}&run_id={run.id}", status_code=303)
