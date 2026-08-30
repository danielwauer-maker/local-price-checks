from __future__ import annotations

from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import _admin
from .coverage_models import StoreDiscoveryCandidate
from .db import get_db
from .geo import haversine_km
from .models import Store
from .postcode_coverage_service import candidate_ready_for_promotion, verify_staged_candidate

router = APIRouter()
templates = Jinja2Templates(directory=__import__("pathlib").Path(__file__).resolve().parent / "templates")


def _address_geocode(candidate: StoreDiscoveryCandidate) -> dict | None:
    """Return a conservative address reference point for manual admin review."""
    if not candidate.address or not candidate.postal_code or not candidate.city:
        return None
    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "street": candidate.address,
                "postalcode": candidate.postal_code,
                "city": candidate.city,
                "country": "Germany",
                "countrycodes": "de",
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 5,
            },
            headers={"User-Agent": "Spareno/1.0 admin-coordinate-review"},
            timeout=10,
        )
        response.raise_for_status()
    except Exception:
        return None

    rows = []
    for row in response.json():
        address = row.get("address") or {}
        if str(address.get("postcode") or "")[:5] != candidate.postal_code:
            continue
        try:
            lat = float(row["lat"])
            lng = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(
            {
                "lat": lat,
                "lng": lng,
                "display_name": row.get("display_name") or candidate.address,
                "distance_m": round(
                    haversine_km(candidate.latitude, candidate.longitude, lat, lng) * 1000.0,
                    1,
                ),
            }
        )
    if not rows:
        return None
    return min(rows, key=lambda row: row["distance_m"])


@router.post("/admin/coverage/candidates/{candidate_id}/verify")
def verify_candidate_and_open_coordinate_review(
    candidate_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    """Run the existing automatic check, then always show its two points visually.

    This route is intentionally registered before the legacy handler with the
    same path. Existing admin buttons therefore keep working while manual
    coordinate verification gains an explicit review screen.
    """
    try:
        candidate = verify_staged_candidate(db, candidate_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse(
        f"/admin/coverage/candidates/{candidate.id}/coordinate-review",
        status_code=303,
    )


@router.get("/admin/coverage/candidates/{candidate_id}/coordinate-review")
def coordinate_review(
    candidate_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Marktkandidat nicht gefunden")
    store = db.get(Store, candidate.matched_store_id) if candidate.matched_store_id else None
    address_point = _address_geocode(candidate)
    return templates.TemplateResponse(
        "admin_candidate_coordinate_review.html",
        {
            "request": request,
            "actor": actor,
            "candidate": candidate,
            "store": store,
            "address_point": address_point,
            "candidate_ready_for_promotion": candidate_ready_for_promotion,
        },
    )


@router.post("/admin/coverage/candidates/{candidate_id}/address-confirm")
def confirm_candidate_address(
    candidate_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    """Allow an admin to confirm the visible market address as its own identity gate."""
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Marktkandidat nicht gefunden")
    if not candidate.address or not candidate.postal_code or not candidate.city:
        raise HTTPException(400, "Vollständige Adresse, PLZ und Ort sind für die Adressbestätigung erforderlich")

    candidate.address_verified = True
    candidate.status = "verified" if candidate_ready_for_promotion(candidate) else "discovered"
    candidate.updated_at = datetime.utcnow()
    manual_note = "Adresse manuell im Admin bestätigt"
    candidate.verification_note = (
        f"{candidate.verification_note}; {manual_note}"
        if candidate.verification_note
        else manual_note
    )
    audit(
        db,
        "candidate_address_confirmed",
        "store_candidate",
        candidate.id,
        f"address={candidate.address};postal_code={candidate.postal_code};city={candidate.city}",
        actor,
    )
    db.commit()
    return RedirectResponse(
        f"/admin/coverage/candidates/{candidate.id}/coordinate-review",
        status_code=303,
    )


@router.post("/admin/coverage/candidates/{candidate_id}/coordinate-review")
def save_coordinate_review(
    candidate_id: int,
    latitude: float = Form(...),
    longitude: float = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Marktkandidat nicht gefunden")
    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        raise HTTPException(400, "Ungültige Koordinaten")
    if not candidate.address_verified:
        raise HTTPException(400, "Adresse muss vor der manuellen Positionsfreigabe bestätigt sein")

    old_latitude = candidate.latitude
    old_longitude = candidate.longitude
    candidate.latitude = float(latitude)
    candidate.longitude = float(longitude)
    candidate.coordinates_verified = True
    candidate.verified_at = datetime.utcnow()
    candidate.status = "verified" if candidate_ready_for_promotion(candidate) else "discovered"
    manual_note = (
        "Position manuell im Admin bestätigt; "
        f"vorher={old_latitude:.6f},{old_longitude:.6f}; "
        f"neu={candidate.latitude:.6f},{candidate.longitude:.6f}"
    )
    candidate.verification_note = (
        f"{candidate.verification_note}; {manual_note}"
        if candidate.verification_note
        else manual_note
    )
    candidate.updated_at = datetime.utcnow()

    store = db.get(Store, candidate.matched_store_id) if candidate.matched_store_id else None
    if store is not None:
        store.latitude = candidate.latitude
        store.longitude = candidate.longitude

    audit(
        db,
        "candidate_coordinates_confirmed",
        "store_candidate",
        candidate.id,
        f"lat={candidate.latitude:.6f};lng={candidate.longitude:.6f};store={store.id if store else '-'}",
        actor,
    )
    db.commit()
    return RedirectResponse(
        f"/admin/coverage?result=candidate:{candidate.id}:coordinates-confirmed#postcode-{candidate.postal_code}",
        status_code=303,
    )
