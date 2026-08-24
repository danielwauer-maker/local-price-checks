from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .api_routes import _price_payload
from .db import get_db
from .services import current_user, offers_for_selected_stores

router = APIRouter(prefix="/api")


@router.get("/offers/upcoming")
def upcoming_offers(db: Session = Depends(get_db)):
    """Return released local offers starting after today within the next 14 days.

    The selected-store release/radius rules are shared with the current offer
    view. Keeping upcoming prices outside /bootstrap prevents future offers from
    accidentally participating in today's shopping-plan calculations.
    """
    user = current_user(db)
    rows = offers_for_selected_stores(db, user, "next")
    starts = sorted({row.valid_from for row in rows})
    return {
        "count": len(rows),
        "startsOn": starts[0].isoformat() if starts else None,
        "prices": [_price_payload(row, db) for row in rows],
    }
