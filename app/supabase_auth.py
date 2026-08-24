from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

from .config import settings


@dataclass(frozen=True)
class VerifiedSupabaseUser:
    user_id: str
    email: str | None


def verify_supabase_access_token(token: str) -> VerifiedSupabaseUser:
    """Validate a Supabase access token against the project's Auth server.

    This deliberately avoids trusting browser-provided identity claims. Supabase
    documents GET /auth/v1/user with the publishable key + bearer token as a
    valid verification path for access tokens, including projects still using
    legacy HS256 signing keys.
    """
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth ist im Backend noch nicht konfiguriert.",
        )
    if not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Fehlendes Access-Token")

    url = f"{settings.supabase_url}/auth/v1/user"
    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {token.strip()}",
    }
    try:
        response = httpx.get(url, headers=headers, timeout=8.0)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth ist vorübergehend nicht erreichbar.",
        ) from exc

    if response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültige oder abgelaufene Session")

    payload = response.json()
    subject = str(payload.get("id") or "").strip()
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Supabase-Session ohne Benutzer-ID")
    email = payload.get("email")
    return VerifiedSupabaseUser(user_id=subject, email=str(email).strip() if email else None)
