from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .db import get_db
from .models import Store
from .market_activation import store_is_public
from .prospect_models import Prospect
from .prospects import ensure_store_prospects, discover_and_store_prospect

router = APIRouter(prefix="/api/prospects")


def _payload(row: Prospect | None):
    if not row:
        return None
    return {
        "id": row.id,
        "period": row.period_key,
        "validFrom": row.valid_from.isoformat() if row.valid_from else None,
        "validTo": row.valid_to.isoformat() if row.valid_to else None,
        "pageCount": row.page_count,
        "viewerUrl": f"/api/prospects/{row.id}/file",
        "sourceUrl": row.source_url,
        "fetchedAt": row.fetched_at.isoformat() if row.fetched_at else None,
    }


@router.get("/stores/{store_id}")
def store_prospects(store_id: int, db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if not store_is_public(store):
        raise HTTPException(404, "Market not found")
    current, nxt = ensure_store_prospects(db, store)
    return {"current": _payload(current), "next": _payload(nxt)}


@router.post("/stores/{store_id}/refresh")
def refresh_store_prospects(store_id: int, db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if not store_is_public(store):
        raise HTTPException(404, "Market not found")
    result = {}
    for period in ("current", "next"):
        if period == "next" and store.retailer != "Netto Marken-Discount":
            result[period] = None
            continue
        try:
            result[period] = _payload(discover_and_store_prospect(db, store, period))
        except Exception as exc:
            result[period] = {"error": str(exc)}
    return result


@router.get("/{prospect_id}/file")
def prospect_file(prospect_id: int, db: Session = Depends(get_db)):
    row = db.get(Prospect, prospect_id)
    if not row or not row.active or not store_is_public(db.get(Store, row.store_id)):
        raise HTTPException(404, "Prospect not found")
    target = Path(row.local_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "Prospect file missing")
    return FileResponse(target, media_type="application/pdf", filename=f"prospekt-{row.store_id}-{row.period_key}.pdf", content_disposition_type="inline")
