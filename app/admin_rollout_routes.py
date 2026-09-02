from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import _admin
from .collection_quality import CollectionQualitySnapshot
from .coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from .db import get_db
from .market_activation import StoreActivationState, StoreQualityAssessment, activation_overview
from .models import CollectionRun, FavoriteStore, MediaAsset, Offer, Store
from .physical_market_identity import canonical_store_map, collapse_physical_stores, duplicate_groups
from .postcode_coverage_service import candidate_ready_for_promotion
from .postcode_reconciliation import deduplicate_candidates
from .prospect_models import Prospect, ProspectArchive
from .retailer_capabilities import retailer_capabilities
from .scrape_health import scrape_health_rows

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


def _step_state(store: Store, overview) -> tuple[str, str]:
    if store.benchmark_verified and store.active:
        return "public", "Öffentlich"
    state = getattr(overview, "state", None)
    state_value = getattr(state, "status", None) or getattr(state, "activation_status", None)
    if state_value:
        return str(state_value), str(state_value).replace("_", " ").title()
    latest_run = getattr(overview, "latest_run", None)
    if latest_run and latest_run.status in {"success", "warning"}:
        return "quality", "Qualität prüfen"
    return "test", "Test-Scrape"


def _delete_blockers(db: Session, store: Store) -> list[str]:
    blockers: list[str] = []
    if store.benchmark_verified:
        blockers.append("Markt ist öffentlich/freigegeben")
    checks = (
        (Offer, "store_id", "Angebote"),
        (CollectionRun, "store_id", "Collector-Läufe"),
        (FavoriteStore, "store_id", "Nutzer-Favoriten"),
        (Prospect, "store_id", "Prospekte"),
        (ProspectArchive, "store_id", "Prospekt-Archive"),
        (MediaAsset, "store_id", "Marktmedien"),
    )
    for model, field_name, label in checks:
        if db.query(model).filter(getattr(model, field_name) == store.id).first():
            blockers.append(label)
    return blockers


@router.post("/admin/rollout/stores/{store_id}/delete")
def delete_false_store(
    store_id: int,
    confirm: str = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    # Deliberately use the exact row, not the canonical alias mapping: the
    # administrator must be able to remove one wrong alias without deleting the
    # real physical market that represents the group.
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Markt nicht gefunden")
    if confirm.strip() != "LOESCHEN":
        raise HTTPException(400, "Zum endgültigen Löschen exakt LOESCHEN eingeben")
    blockers = _delete_blockers(db, store)
    if blockers:
        raise HTTPException(400, "Markt kann nicht gelöscht werden: " + ", ".join(blockers))

    # Preserve discovery provenance but reject the wrong mapping so the same
    # candidate cannot silently promote the bad Store row again.
    candidates = db.query(StoreDiscoveryCandidate).filter_by(matched_store_id=store.id).all()
    for candidate in candidates:
        candidate.matched_store_id = None
        candidate.status = "rejected"
        note = "Store-Zeile im Admin als falscher Markt gelöscht."
        candidate.verification_note = f"{candidate.verification_note}; {note}" if candidate.verification_note else note

    db.query(StoreQualityAssessment).filter_by(store_id=store.id).delete(synchronize_session=False)
    db.query(CollectionQualitySnapshot).filter_by(store_id=store.id).delete(synchronize_session=False)
    db.query(StoreActivationState).filter_by(store_id=store.id).delete(synchronize_session=False)
    audit(db, "false_store_deleted", "store", store.id, f"{store.retailer} | {store.name} | {store.address}", actor)
    db.delete(store)
    db.commit()
    return RedirectResponse("/admin/rollout?deleted=1", status_code=303)


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

    deletable = {store.id: not _delete_blockers(db, store) for store in raw_stores}
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
            "deletable": deletable,
            "progress": progress,
            "candidate_ready_for_promotion": candidate_ready_for_promotion,
        },
    )
