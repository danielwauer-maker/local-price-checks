from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from .client_context import get_client_key
from .config import settings
from .db import get_db
from .feature_flags import feature_enabled
from .lokero_models import ReviewerDeviceGrant

security = HTTPBasic(auto_error=False)


def _valid_admin(credentials: HTTPBasicCredentials | None) -> str | None:
    if credentials is None or not settings.admin_password:
        return None
    user_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    pass_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    return credentials.username if user_ok and pass_ok else None


def reviewer_device(db: Session) -> ReviewerDeviceGrant | None:
    key = get_client_key()
    if not key:
        return None
    grant = db.get(ReviewerDeviceGrant, key)
    if not grant:
        return None
    if grant.expires_at <= datetime.utcnow():
        db.delete(grant)
        db.commit()
        return None
    grant.last_used_at = datetime.utcnow()
    db.commit()
    return grant


def require_reviewer(db: Session = Depends(get_db)) -> str:
    if not feature_enabled(db, "reviewer_mode"):
        raise HTTPException(status_code=404, detail="Not found")
    grant = reviewer_device(db)
    if not grant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer mode not enabled for this device")
    return grant.granted_by or "reviewer-device"


def unlock_reviewer_device(
    credentials: HTTPBasicCredentials | None,
    db: Session,
    *,
    days: int = 30,
    label: str | None = None,
) -> ReviewerDeviceGrant:
    actor = _valid_admin(credentials)
    if not actor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin credentials required",
            headers={"WWW-Authenticate": "Basic"},
        )
    key = get_client_key()
    if not key:
        raise HTTPException(status_code=400, detail="Client device identity missing")
    grant = db.get(ReviewerDeviceGrant, key)
    if not grant:
        grant = ReviewerDeviceGrant(client_key=key)
        db.add(grant)
    grant.label = (label or "Lokero Prüfgerät").strip()[:120]
    grant.granted_by = actor
    grant.expires_at = datetime.utcnow() + timedelta(days=max(1, min(days, 90)))
    grant.last_used_at = datetime.utcnow()
    db.commit()
    db.refresh(grant)
    return grant


def lock_reviewer_device(db: Session) -> bool:
    key = get_client_key()
    if not key:
        return False
    grant = db.get(ReviewerDeviceGrant, key)
    if not grant:
        return False
    db.delete(grant)
    db.commit()
    return True
