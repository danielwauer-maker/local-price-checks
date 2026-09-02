from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_routes import _admin
from .coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from .db import get_db
from .market_activation import activation_overview
from .models import Store
from .physical_market_identity import canonical_store_map, collapse_physical_stores, duplicate_groups
from .postcode_coverage_service import candidate_ready_for_promotion
from .postcode_reconciliation import deduplicate_candidates
from .retailer_capabilities import retailer_capabilities
from .scrape_health import scrape_health_rows

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


_LIFECYCLE_LABELS = {
    "discovered": "Entdeckt",
    "identity_verified": "Identität geprüft",
    "promoted": "Bereit für Test-Scrape",
    "scrape_pending": "Test-Scrape läuft",
    "scrape_failed": "Test-Scrape fehlgeschlagen",
    "quality_review": "Qualität prüfen",
    "quality_passed": "Quality Gate bestanden",
    "public": "Öffentlich",
    "suspended": "Gesperrt",
}


def _step_state(store: Store, overview) -> tuple[str, str]:
    if store.benchmark_verified and store.active:
        return "public", "Öffentlich"
    state = getattr(overview, "state", None)
    state_value = getattr(state, "lifecycle_status", None)
    if state_value:
        value = str(state_value)
        return value, _LIFECYCLE_LABELS.get(value, value.replace("_", " ").title())
    latest_run = getattr(overview, "latest_run", None)
    if latest_run and latest_run.status in {"success", "warning"}:
        return "quality", "Qualität prüfen"
    return "test", "Test-Scrape"


@router.get("/admin/rollout")
def rollout_admin(
    request: Request,
    retailer: str = Query("REWE"),
    postal_code: str = Query(""),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    capabilities = retailer_capabilities()
    allowed = {row.retailer for row in capabilities if row.rollout_enabled}
    selected_retailer = retailer if retailer in allowed else "REWE"

    postcodes = (
        db.query(CoveragePostalCode)
        .filter(CoveragePostalCode.enabled.is_(True))
        .order_by(CoveragePostalCode.postal_code)
        .all()
    )
    selected_postcode = postal_code.strip()
    if selected_postcode and selected_postcode not in {row.postal_code for row in postcodes}:
        selected_postcode = ""

    candidate_query = db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.retailer == selected_retailer
    )
    store_query = db.query(Store).filter(Store.retailer == selected_retailer)
    if selected_postcode:
        candidate_query = candidate_query.filter(StoreDiscoveryCandidate.postal_code == selected_postcode)
        store_query = store_query.filter(Store.postal_code == selected_postcode)

    raw_candidates = candidate_query.order_by(
        StoreDiscoveryCandidate.postal_code,
        StoreDiscoveryCandidate.name,
    ).all()
    grouped_candidates: dict[str, list[StoreDiscoveryCandidate]] = defaultdict(list)
    for candidate in raw_candidates:
        grouped_candidates[candidate.postal_code].append(candidate)
    candidates = [
        row
        for postcode_rows in grouped_candidates.values()
        for row in deduplicate_candidates(postcode_rows)
    ]

    raw_stores = store_query.order_by(Store.postal_code, Store.city, Store.name).all()
    stores = collapse_physical_stores(raw_stores)
    overviews = {store.id: activation_overview(db, store) for store in stores}
    step_states = {store.id: _step_state(store, overviews[store.id]) for store in stores}
    health = {row.store_id: row for row in scrape_health_rows(db) if row.retailer == selected_retailer}

    duplicates = duplicate_groups(raw_stores)
    canonical_map = canonical_store_map(raw_stores)
    duplicate_aliases: dict[str, list[dict]] = defaultdict(list)
    for group in duplicates:
        canonical = canonical_map[group[0].id]
        duplicate_aliases[canonical.postal_code].append({
            "canonical": canonical,
            "aliases": group,
        })

    progress = {
        "candidates": len(candidates),
        "identity_ready": sum(1 for row in candidates if candidate_ready_for_promotion(row)),
        "stores": len(stores),
        "public": sum(1 for row in stores if row.active and row.benchmark_verified),
        "duplicate_groups": len(duplicates),
    }

    return templates.TemplateResponse(
        "admin_rollout.html",
        {
            "request": request,
            "actor": actor,
            "admin_section": "rollout",
            "capabilities": capabilities,
            "selected_retailer": selected_retailer,
            "postcodes": postcodes,
            "selected_postcode": selected_postcode,
            "candidates": candidates,
            "stores": stores,
            "overviews": overviews,
            "step_states": step_states,
            "health": health,
            "duplicate_aliases": dict(duplicate_aliases),
            "progress": progress,
            "candidate_ready_for_promotion": candidate_ready_for_promotion,
        },
    )
