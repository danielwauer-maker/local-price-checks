from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .account_linking import AccountLinkConflict, account_profile_for_client, link_verified_identity
from .client_context import get_client_key
from .client_models import AccountIdentity, UserClient
from .db import get_db
from .services import current_user
from .supabase_auth import verify_supabase_access_token

router = APIRouter(prefix="/api/account", tags=["account"])


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization fehlt")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger Authorization-Header")
    return token.strip()


def _current_client(db: Session) -> UserClient:
    # Ensure the anonymous profile/client exists before linking.
    current_user(db)
    key = get_client_key()
    if not key:
        raise HTTPException(status_code=400, detail="Kein Geräte-Client im Request")
    client = db.query(UserClient).filter(UserClient.client_key == key).first()
    if not client:
        raise HTTPException(status_code=400, detail="Geräte-Client konnte nicht aufgelöst werden")
    return client


@router.post("/link")
def link_account(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    verified = verify_supabase_access_token(_bearer_token(authorization))
    client = _current_client(db)
    try:
        profile = link_verified_identity(
            db,
            client=client,
            provider="supabase",
            provider_subject=verified.user_id,
            email=verified.email,
        )
    except AccountLinkConflict as exc:
        raise HTTPException(status_code=409, detail="Dieses Gerät ist bereits mit einem anderen Konto verknüpft.") from exc

    return {
        "linked": True,
        "profileId": profile.id,
        "email": verified.email,
    }


@router.get("/status")
def account_status(db: Session = Depends(get_db)):
    key = get_client_key()
    if not key:
        return {"linked": False}
    client = db.query(UserClient).filter(UserClient.client_key == key).first()
    if not client:
        return {"linked": False}
    profile = account_profile_for_client(db, client)
    if profile is None:
        return {"linked": False, "profileId": client.user_id}
    link_identity = (
        db.query(AccountIdentity)
        .join(AccountIdentity.client_links)
        .filter_by(client_id=client.id)
        .first()
    )
    return {
        "linked": True,
        "profileId": profile.id,
        "email": link_identity.email if link_identity else None,
    }
