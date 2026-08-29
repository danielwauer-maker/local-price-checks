"""Seed the isolated SQLite database used by browser/backend/SSE integration tests."""

from __future__ import annotations

from app import model_registry as _model_registry  # noqa: F401
from app.client_models import (
    AccountAppPreferences,
    AccountClientLink,
    AccountIdentity,
    UserClient,
)
from app.db import Base, SessionLocal, engine
from app.models import MasterProduct, UserProfile
from app.sharing_models import (
    SharedShoppingList,
    SharedShoppingListMember,
    SharedShoppingListUserState,
)


CLIENT_A1 = "spareno-e2e-device-a1-001"
CLIENT_A2 = "spareno-e2e-device-a2-002"
CLIENT_B1 = "spareno-e2e-device-b1-003"


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        account_a = UserProfile(display_name="Realtime Alice", postal_code="56269", city="Dierdorf")
        account_b = UserProfile(display_name="Realtime Bob", postal_code="56269", city="Dierdorf")
        shadow_a2 = UserProfile(display_name="Device shadow A2")
        db.add_all([account_a, account_b, shadow_a2])
        db.flush()

        client_a1 = UserClient(client_key=CLIENT_A1, user_id=account_a.id)
        client_a2 = UserClient(client_key=CLIENT_A2, user_id=shadow_a2.id)
        client_b1 = UserClient(client_key=CLIENT_B1, user_id=account_b.id)
        db.add_all([client_a1, client_a2, client_b1])
        db.flush()

        identity_a = AccountIdentity(
            user_id=account_a.id,
            provider="e2e",
            provider_subject="account-a",
            email="alice@example.test",
        )
        identity_b = AccountIdentity(
            user_id=account_b.id,
            provider="e2e",
            provider_subject="account-b",
            email="bob@example.test",
        )
        db.add_all([identity_a, identity_b])
        db.flush()
        db.add_all(
            [
                AccountClientLink(identity_id=identity_a.id, client_id=client_a1.id),
                AccountClientLink(identity_id=identity_a.id, client_id=client_a2.id),
                AccountClientLink(identity_id=identity_b.id, client_id=client_b1.id),
            ]
        )
        db.add(AccountAppPreferences(user_id=account_a.id))
        db.add(MasterProduct(id=1, name="E2E Butter", brand="Spareno Test", package_size="250 g", normalized_key="e2e-butter"))

        shared = SharedShoppingList(
            owner_user_id=account_a.id,
            name="E2E Familienliste",
            is_personal=False,
            revision=1,
        )
        db.add(shared)
        db.flush()
        db.add_all(
            [
                SharedShoppingListMember(list_id=shared.id, user_id=account_a.id, role="owner"),
                SharedShoppingListMember(list_id=shared.id, user_id=account_b.id, role="editor"),
                SharedShoppingListUserState(user_id=account_a.id, active_list_id=shared.id),
                SharedShoppingListUserState(user_id=account_b.id, active_list_id=shared.id),
            ]
        )
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
