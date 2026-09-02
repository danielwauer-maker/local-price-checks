from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .admin_routes import _admin
from .coverage_models import StoreDiscoveryCandidate
from .db import get_db
from .market_identity_conflicts import weak_candidate_promotion_conflict
from .postcode_coverage_service import promote_candidate_to_store

router = APIRouter()


@router.post("/admin/coverage/candidates/{candidate_id}/promote")
def guarded_promote_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Marktkandidat nicht gefunden")

    conflict = weak_candidate_promotion_conflict(db, candidate)
    if conflict.blocked:
        raise HTTPException(409, conflict.reason or "Möglicher physischer Doppelmarkt")

    try:
        store = promote_candidate_to_store(db, candidate_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(
        f"/admin/coverage?result=candidate:{candidate_id}:store={store.id}",
        status_code=303,
    )
