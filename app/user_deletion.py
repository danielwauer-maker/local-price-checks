from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .activity_models import ClientActivityDay, ClientFeatureUsage, ClientUsageSession
from .client_models import (
    AccountClientLink,
    AccountIdentity,
    ClientAppRating,
    ClientDevice,
    ClientPricingFeedback,
    UserClient,
)
from .lokero_models import (
    FavoriteProductFamily,
    FavoriteProductPreference,
    RegionInterest,
    ReviewerDeviceGrant,
)
from .models import FavoriteProduct, FavoriteStore, ShoppingItem, UserProfile


class RegisteredAccountDeletionBlocked(RuntimeError):
    """Raised when the anonymous-test-user action targets a registered account."""


@dataclass(frozen=True)
class UserDeletionResult:
    user_id: int
    display_name: str
    client_count: int


def is_registered_user(db: Session, user_id: int) -> bool:
    return db.query(AccountIdentity.id).filter(AccountIdentity.user_id == user_id).first() is not None


def delete_anonymous_user(db: Session, user_id: int) -> UserDeletionResult | None:
    """Delete one anonymous Lokero profile and all data owned by its client/profile.

    This function intentionally refuses profiles that already have a verified
    external account identity. Registered-account deletion needs a separate
    account lifecycle flow because it must also revoke the external auth
    identity. The admin action is therefore safe for today's test/anonymous
    profiles and cannot silently orphan a Supabase account later.

    The caller controls the transaction and must commit or roll back.
    """

    user = db.get(UserProfile, user_id)
    if user is None:
        return None
    if is_registered_user(db, user_id):
        raise RegisteredAccountDeletionBlocked(
            "Registrierte Konten können nicht über die Testnutzer-Löschung entfernt werden."
        )

    clients = db.query(UserClient).filter(UserClient.user_id == user_id).all()
    client_ids = [client.id for client in clients]
    client_keys = [client.client_key for client in clients]

    if client_ids:
        # Links can point to an identity owned by another canonical profile, so
        # remove only links for the clients being deleted.
        db.query(AccountClientLink).filter(AccountClientLink.client_id.in_(client_ids)).delete(
            synchronize_session=False
        )
        db.query(ClientUsageSession).filter(ClientUsageSession.client_id.in_(client_ids)).delete(
            synchronize_session=False
        )
        db.query(ClientActivityDay).filter(ClientActivityDay.client_id.in_(client_ids)).delete(
            synchronize_session=False
        )
        db.query(ClientFeatureUsage).filter(ClientFeatureUsage.client_id.in_(client_ids)).delete(
            synchronize_session=False
        )
        db.query(ClientDevice).filter(ClientDevice.client_id.in_(client_ids)).delete(
            synchronize_session=False
        )
        db.query(ClientPricingFeedback).filter(ClientPricingFeedback.client_id.in_(client_ids)).delete(
            synchronize_session=False
        )
        db.query(ClientAppRating).filter(ClientAppRating.client_id.in_(client_ids)).delete(
            synchronize_session=False
        )

    if client_keys:
        db.query(ReviewerDeviceGrant).filter(ReviewerDeviceGrant.client_key.in_(client_keys)).delete(
            synchronize_session=False
        )

    # Profile-owned state. Keep this explicit so future sharing/account tables
    # must consciously define deletion semantics instead of being removed by a
    # broad table-name heuristic.
    db.query(FavoriteProductPreference).filter(FavoriteProductPreference.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(FavoriteProductFamily).filter(FavoriteProductFamily.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(RegionInterest).filter(RegionInterest.user_id == user_id).delete(synchronize_session=False)
    db.query(FavoriteStore).filter(FavoriteStore.user_id == user_id).delete(synchronize_session=False)
    db.query(FavoriteProduct).filter(FavoriteProduct.user_id == user_id).delete(synchronize_session=False)
    db.query(ShoppingItem).filter(ShoppingItem.user_id == user_id).delete(synchronize_session=False)
    db.query(ClientPricingFeedback).filter(ClientPricingFeedback.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(ClientAppRating).filter(ClientAppRating.user_id == user_id).delete(synchronize_session=False)

    if client_ids:
        db.query(UserClient).filter(UserClient.id.in_(client_ids)).delete(synchronize_session=False)

    # Defensive: there should be no AccountIdentity here because of the guard.
    db.query(AccountIdentity).filter(AccountIdentity.user_id == user_id).delete(synchronize_session=False)
    db.delete(user)

    return UserDeletionResult(
        user_id=user_id,
        display_name=user.display_name or f"Nutzer #{user_id}",
        client_count=len(client_ids),
    )
