from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .client_models import AccountClientLink, AccountIdentity, UserClient
from .models import UserProfile


class AccountLinkConflict(ValueError):
    """Raised when one browser client is already linked to another identity."""


def link_verified_identity(
    db: Session,
    *,
    client: UserClient,
    provider: str,
    provider_subject: str,
    email: str | None = None,
) -> UserProfile:
    """Link a provider-verified identity without replacing anonymous profile data.

    The caller must verify the external token before invoking this function.
    On first registration the current anonymous profile becomes the canonical
    account profile, preserving location, radius, favorites and shopping data.
    On later devices the existing identity remains canonical and the device is
    merely attached through ``AccountClientLink``.
    """

    normalized_provider = provider.strip().lower()
    normalized_subject = provider_subject.strip()
    if not normalized_provider or not normalized_subject:
        raise ValueError("provider and provider_subject are required")

    now = datetime.utcnow()
    identity = (
        db.query(AccountIdentity)
        .filter(
            AccountIdentity.provider == normalized_provider,
            AccountIdentity.provider_subject == normalized_subject,
        )
        .first()
    )
    if identity is None:
        identity = AccountIdentity(
            user_id=client.user_id,
            provider=normalized_provider,
            provider_subject=normalized_subject,
            email=email,
            created_at=now,
            last_seen_at=now,
        )
        db.add(identity)
        db.flush()
    else:
        identity.last_seen_at = now
        if email:
            identity.email = email

    existing_link = (
        db.query(AccountClientLink)
        .filter(AccountClientLink.client_id == client.id)
        .first()
    )
    if existing_link and existing_link.identity_id != identity.id:
        raise AccountLinkConflict("client is already linked to another account identity")

    if existing_link is None:
        db.add(
            AccountClientLink(
                identity_id=identity.id,
                client_id=client.id,
                linked_at=now,
                last_seen_at=now,
            )
        )
    else:
        existing_link.last_seen_at = now

    db.commit()
    db.refresh(identity)
    return identity.user


def account_profile_for_client(db: Session, client: UserClient) -> UserProfile | None:
    """Return the canonical account profile for a previously linked client."""

    link = (
        db.query(AccountClientLink)
        .filter(AccountClientLink.client_id == client.id)
        .first()
    )
    if link is None:
        return None
    link.last_seen_at = datetime.utcnow()
    link.identity.last_seen_at = link.last_seen_at
    db.flush()
    return link.identity.user
