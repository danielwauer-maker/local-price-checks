from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .account_routes import _account_state_payload, _linked_profile
from .db import get_db
from .geo import resolve_center
from .services import current_user

router = APIRouter(prefix="/api/account", tags=["account"])


class ProfileLocationPayload(BaseModel):
    displayName: str | None = Field(default=None, max_length=100)
    postalCode: str = Field(min_length=3, max_length=10)
    city: str = Field(min_length=1, max_length=100)
    radiusKm: float | None = Field(default=None, ge=1, le=50)


@router.put("/profile")
def update_account_profile(payload: ProfileLocationPayload, db: Session = Depends(get_db)):
    profile = _linked_profile(db) or current_user(db)
    postal_code = payload.postalCode.strip()
    city = " ".join(payload.city.strip().split())
    center = resolve_center(postal_code, city)
    if center is None:
        raise HTTPException(400, "PLZ und Ort konnten nicht eindeutig gefunden werden.")

    if payload.displayName is not None:
        name = " ".join(payload.displayName.strip().split())
        if name:
            profile.display_name = name
    profile.postal_code = postal_code
    profile.city = city
    profile.latitude, profile.longitude = center
    if payload.radiusKm is not None:
        profile.radius_km = max(1.0, min(float(payload.radiusKm), 50.0))
    db.commit()
    db.refresh(profile)
    return _account_state_payload(db, profile)
