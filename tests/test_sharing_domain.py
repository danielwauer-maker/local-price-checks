from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.sharing_routes as sharing_routes
from app.db import SessionLocal, engine
from app.models import FavoriteProduct, MasterProduct, ShoppingItem, UserProfile
from app.sharing_models import (
    FavoriteShare,
    FavoriteShareItemVisibility,
    FavoriteShareSubscription,
    SharedShoppingList,
    SharedShoppingListInvite,
    SharedShoppingListItem,
    SharedShoppingListMember,
    SharedShoppingListUserState,
)
from app.sharing_routes import _ensure_personal_list, _snapshot, _visible_favorite_ids, public_favorites


def _ensure_tables() -> None:
    UserProfile.__table__.create(bind=engine, checkfirst=True)
    MasterProduct.__table__.create(bind=engine, checkfirst=True)
    ShoppingItem.__table__.create(bind=engine, checkfirst=True)
    SharedShoppingList.__table__.create(bind=engine, checkfirst=True)
    SharedShoppingListMember.__table__.create(bind=engine, checkfirst=True)
    SharedShoppingListInvite.__table__.create(bind=engine, checkfirst=True)
    SharedShoppingListItem.__table__.create(bind=engine, checkfirst=True)
    SharedShoppingListUserState.__table__.create(bind=engine, checkfirst=True)
    FavoriteShare.__table__.create(bind=engine, checkfirst=True)
    FavoriteShareItemVisibility.__table__.create(bind=engine, checkfirst=True)
    FavoriteShareSubscription.__table__.create(bind=engine, checkfirst=True)


def _cleanup(db, user_ids: list[int], product_ids: list[int]) -> None:
    db.rollback()
    db.query(FavoriteShareSubscription).filter(FavoriteShareSubscription.subscriber_user_id.in_(user_ids)).delete(synchronize_session=False)
    share_ids = [row[0] for row in db.query(FavoriteShare.id).filter(FavoriteShare.owner_user_id.in_(user_ids)).all()]
    if share_ids:
        db.query(FavoriteShareSubscription).filter(FavoriteShareSubscription.share_id.in_(share_ids)).delete(synchronize_session=False)
    db.query(FavoriteShareItemVisibility).filter(FavoriteShareItemVisibility.owner_user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(FavoriteShare).filter(FavoriteShare.owner_user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(SharedShoppingListInvite).filter(SharedShoppingListInvite.created_by_user_id.in_(user_ids)).delete(synchronize_session=False)
    list_ids = [row[0] for row in db.query(SharedShoppingList.id).filter(SharedShoppingList.owner_user_id.in_(user_ids)).all()]
    if list_ids:
        db.query(SharedShoppingListUserState).filter(SharedShoppingListUserState.active_list_id.in_(list_ids)).delete(synchronize_session=False)
        db.query(SharedShoppingListItem).filter(SharedShoppingListItem.list_id.in_(list_ids)).delete(synchronize_session=False)
        db.query(SharedShoppingListMember).filter(SharedShoppingListMember.list_id.in_(list_ids)).delete(synchronize_session=False)
        db.query(SharedShoppingList).filter(SharedShoppingList.id.in_(list_ids)).delete(synchronize_session=False)
    db.query(SharedShoppingListUserState).filter(SharedShoppingListUserState.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(FavoriteProduct).filter(FavoriteProduct.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(ShoppingItem).filter(ShoppingItem.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(UserProfile).filter(UserProfile.id.in_(user_ids)).delete(synchronize_session=False)
    db.query(MasterProduct).filter(MasterProduct.id.in_(product_ids)).delete(synchronize_session=False)
    db.commit()


def test_personal_shared_list_imports_legacy_basket_once():
    _ensure_tables()
    db = SessionLocal()
    user_ids: list[int] = []
    product_ids: list[int] = []
    try:
        user = UserProfile(display_name="Sharing Owner", radius_km=15)
        product = MasterProduct(name="Sharing Milch", normalized_key="sharing-milch")
        db.add_all([user, product])
        db.flush()
        user_ids.append(user.id)
        product_ids.append(product.id)
        db.add(ShoppingItem(user_id=user.id, master_product_id=product.id, quantity=2))
        db.commit()

        first = _ensure_personal_list(db, user)
        second = _ensure_personal_list(db, user)

        assert first.id == second.id
        assert first.is_personal is True
        assert db.query(SharedShoppingListMember).filter_by(list_id=first.id, user_id=user.id, role="owner").count() == 1
        items = db.query(SharedShoppingListItem).filter_by(list_id=first.id, master_product_id=product.id).all()
        assert len(items) == 1
        assert items[0].quantity == 2
        state = db.get(SharedShoppingListUserState, user.id)
        assert state is not None and state.active_list_id == first.id
    finally:
        if user_ids or product_ids:
            _cleanup(db, user_ids, product_ids)
        db.close()


def test_shared_snapshot_contains_members_and_collaborative_item_state():
    _ensure_tables()
    db = SessionLocal()
    user_ids: list[int] = []
    product_ids: list[int] = []
    try:
        owner = UserProfile(display_name="Owner", radius_km=15)
        partner = UserProfile(display_name="Partner", radius_km=15)
        product = MasterProduct(name="Sharing Kaffee", normalized_key="sharing-kaffee")
        db.add_all([owner, partner, product])
        db.flush()
        user_ids.extend([owner.id, partner.id])
        product_ids.append(product.id)
        shopping_list = SharedShoppingList(owner_user_id=owner.id, name="Familie", revision=7)
        db.add(shopping_list)
        db.flush()
        owner_member = SharedShoppingListMember(list_id=shopping_list.id, user_id=owner.id, role="owner")
        db.add_all([
            owner_member,
            SharedShoppingListMember(list_id=shopping_list.id, user_id=partner.id, role="editor"),
            SharedShoppingListItem(
                list_id=shopping_list.id,
                master_product_id=product.id,
                quantity=3,
                checked=True,
                added_by_user_id=partner.id,
                checked_by_user_id=owner.id,
            ),
        ])
        db.commit()

        snapshot = _snapshot(db, shopping_list, owner_member)
        assert snapshot["list"]["name"] == "Familie"
        assert snapshot["list"]["memberCount"] == 2
        assert snapshot["list"]["revision"] == 7
        assert snapshot["items"][0]["productId"] == str(product.id)
        assert snapshot["items"][0]["checked"] is True
        assert snapshot["items"][0]["addedBy"] == "Partner"
        assert snapshot["items"][0]["checkedBy"] == "Owner"
    finally:
        if user_ids or product_ids:
            _cleanup(db, user_ids, product_ids)
        db.close()


def test_shopping_invite_is_single_use(monkeypatch):
    _ensure_tables()
    db = SessionLocal()
    user_ids: list[int] = []
    product_ids: list[int] = []
    try:
        owner = UserProfile(display_name="Invite Owner", radius_km=15)
        partner = UserProfile(display_name="Invite Partner", radius_km=15)
        db.add_all([owner, partner])
        db.flush()
        user_ids.extend([owner.id, partner.id])
        shopping_list = SharedShoppingList(owner_user_id=owner.id, name="Familie", revision=1)
        db.add(shopping_list)
        db.flush()
        db.add(SharedShoppingListMember(list_id=shopping_list.id, user_id=owner.id, role="owner"))
        invite = SharedShoppingListInvite(
            list_id=shopping_list.id,
            token="single-use-sharing-token",
            created_by_user_id=owner.id,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
        db.add(invite)
        db.commit()

        monkeypatch.setattr(sharing_routes, "_require_linked_user", lambda _db: (partner, SimpleNamespace(email=None)))
        first = sharing_routes.accept_list_invite(invite.token, db)
        assert first["list"]["id"] == str(shopping_list.id)
        assert db.query(SharedShoppingListMember).filter_by(list_id=shopping_list.id, user_id=partner.id).count() == 1

        with pytest.raises(HTTPException) as exc:
            sharing_routes.accept_list_invite(invite.token, db)
        assert exc.value.status_code == 404
        assert db.query(SharedShoppingListMember).filter_by(list_id=shopping_list.id, user_id=partner.id).count() == 1
    finally:
        if user_ids or product_ids:
            _cleanup(db, user_ids, product_ids)
        db.close()


def test_hidden_favorite_and_disabled_share_do_not_leak_public_items():
    _ensure_tables()
    db = SessionLocal()
    user_ids: list[int] = []
    product_ids: list[int] = []
    try:
        owner = UserProfile(display_name="Favorite Owner", radius_km=15)
        visible = MasterProduct(name="Visible Favorite", normalized_key="sharing-visible")
        hidden = MasterProduct(name="Hidden Favorite", normalized_key="sharing-hidden")
        db.add_all([owner, visible, hidden])
        db.flush()
        user_ids.append(owner.id)
        product_ids.extend([visible.id, hidden.id])
        db.add_all([
            FavoriteProduct(user_id=owner.id, master_product_id=visible.id),
            FavoriteProduct(user_id=owner.id, master_product_id=hidden.id),
            FavoriteShareItemVisibility(owner_user_id=owner.id, master_product_id=hidden.id, visible=False),
        ])
        share = FavoriteShare(owner_user_id=owner.id, token="sharing-domain-token", enabled=True)
        db.add(share)
        db.commit()

        assert _visible_favorite_ids(db, owner.id) == [visible.id]
        public = public_favorites(share.token, db)
        assert public["available"] is True
        assert [item["id"] for item in public["items"]] == [str(visible.id)]

        share.enabled = False
        db.commit()
        hidden_public = public_favorites(share.token, db)
        assert hidden_public == {"available": False, "ownerName": "Favorite Owner", "items": []}
    finally:
        if user_ids or product_ids:
            _cleanup(db, user_ids, product_ids)
        db.close()
