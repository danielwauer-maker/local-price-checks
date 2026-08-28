from __future__ import annotations

import json
import threading
from collections import defaultdict

from sqlalchemy import event
from sqlalchemy.orm import Session

from .client_models import AccountAppPreferences
from .db import SessionLocal
from .models import FavoriteProduct, FavoriteStore, Offer, Store, UserProfile
from .push_service import send_push_to_user
from .sharing_models import FavoriteShare, FavoriteShareItemVisibility, FavoriteShareSubscription

_INFO_KEY = "spareno_new_offer_push_candidates"
_LOCK = threading.Lock()
_PENDING: dict[tuple[int, str], dict] = {}
_WINDOW_SECONDS = 20.0


def _favorite_offer_enabled(row: AccountAppPreferences | None) -> bool:
    if row is None:
        return False
    try:
        values = json.loads(row.notifications_json or "{}")
        return bool(values.get("favoriteOffers", False)) if isinstance(values, dict) else False
    except (TypeError, ValueError):
        return False


def _queue_digest(user_id: int, kind: str, product_ids: set[int], friend_name: str | None = None) -> None:
    key = (int(user_id), kind if friend_name is None else f"{kind}:{friend_name}")
    with _LOCK:
        row = _PENDING.get(key)
        if row is None:
            timer = threading.Timer(_WINDOW_SECONDS, _flush_digest, args=(key,))
            timer.daemon = True
            row = {"products": set(), "friend": friend_name, "timer": timer}
            _PENDING[key] = row
            timer.start()
        row["products"].update(product_ids)


def _flush_digest(key: tuple[int, str]) -> None:
    with _LOCK:
        row = _PENDING.pop(key, None)
    if not row:
        return
    user_id = key[0]
    count = len(row["products"])
    if count <= 0:
        return
    friend_name = row.get("friend")
    if friend_name:
        title = "Favoriten von Freunden im Angebot"
        body = f"{count} {'Favorit ist' if count == 1 else 'Favoriten sind'} von {friend_name} aktuell im Angebot."
        tag = f"friend-favorites-{user_id}-{friend_name}"
        data = {"type": "friend_favorite_offer", "count": count}
        url = "/favoriten/freunde"
    else:
        title = "Deine Favoriten im Angebot"
        body = f"{count} deiner {'Favoriten ist' if count == 1 else 'Favoriten sind'} aktuell im Angebot."
        tag = f"favorite-offers-{user_id}"
        data = {"type": "favorite_offer", "count": count}
        url = "/favoriten"
    db = SessionLocal()
    try:
        send_push_to_user(db, user_id, title=title, body=body, url=url, tag=tag, data=data)
    finally:
        db.close()


def _dispatch_candidates(candidates: list[tuple[int, int]]) -> None:
    if not candidates:
        return
    by_store: dict[int, set[int]] = defaultdict(set)
    for store_id, product_id in candidates:
        by_store[int(store_id)].add(int(product_id))

    db = SessionLocal()
    try:
        store_ids = set(by_store)
        product_ids = set().union(*by_store.values()) if by_store else set()
        if not store_ids or not product_ids:
            return

        # Own favorites: only opted-in users and only their favorite markets.
        prefs_by_user = {
            row.user_id: row
            for row in db.query(AccountAppPreferences).filter(AccountAppPreferences.user_id.isnot(None)).all()
            if _favorite_offer_enabled(row)
        }
        if prefs_by_user:
            fav_products: dict[int, set[int]] = defaultdict(set)
            for row in db.query(FavoriteProduct).filter(
                FavoriteProduct.user_id.in_(prefs_by_user.keys()),
                FavoriteProduct.master_product_id.in_(product_ids),
            ).all():
                fav_products[row.user_id].add(row.master_product_id)
            fav_stores: dict[int, set[int]] = defaultdict(set)
            for row in db.query(FavoriteStore).filter(
                FavoriteStore.user_id.in_(prefs_by_user.keys()),
                FavoriteStore.store_id.in_(store_ids),
            ).all():
                fav_stores[row.user_id].add(row.store_id)
            for user_id in prefs_by_user:
                matches = {
                    product_id
                    for store_id in fav_stores.get(user_id, set())
                    for product_id in by_store.get(store_id, set())
                    if product_id in fav_products.get(user_id, set())
                }
                if matches:
                    _queue_digest(user_id, "own", matches)

        # Friend favorites: opt-in is per saved friend. Visibility and share enabled are respected.
        subscriptions = db.query(FavoriteShareSubscription).filter(FavoriteShareSubscription.push_enabled.is_(True)).all()
        for sub in subscriptions:
            share = db.get(FavoriteShare, sub.share_id)
            if share is None or not share.enabled:
                continue
            subscriber = db.get(UserProfile, sub.subscriber_user_id)
            owner = db.get(UserProfile, share.owner_user_id)
            if subscriber is None or owner is None:
                continue
            subscriber_store_ids = {
                row.store_id
                for row in db.query(FavoriteStore).filter(
                    FavoriteStore.user_id == subscriber.id,
                    FavoriteStore.store_id.in_(store_ids),
                ).all()
            }
            if not subscriber_store_ids:
                continue
            owner_favorites = {
                row.master_product_id
                for row in db.query(FavoriteProduct).filter(
                    FavoriteProduct.user_id == owner.id,
                    FavoriteProduct.master_product_id.in_(product_ids),
                ).all()
            }
            hidden = {
                row.master_product_id
                for row in db.query(FavoriteShareItemVisibility).filter(
                    FavoriteShareItemVisibility.owner_user_id == owner.id,
                    FavoriteShareItemVisibility.visible.is_(False),
                    FavoriteShareItemVisibility.master_product_id.in_(product_ids),
                ).all()
            }
            visible = owner_favorites - hidden
            matches = {
                product_id
                for store_id in subscriber_store_ids
                for product_id in by_store.get(store_id, set())
                if product_id in visible
            }
            if matches:
                friend_name = (owner.display_name or "Spareno-Freund").strip()
                _queue_digest(subscriber.id, "friend", matches, friend_name=friend_name)
    finally:
        db.close()


@event.listens_for(Session, "after_flush")
def _collect_new_offers(session: Session, _flush_context) -> None:
    rows = session.info.setdefault(_INFO_KEY, [])
    for offer in session.new:
        if isinstance(offer, Offer) and bool(offer.local_store_offer):
            rows.append((int(offer.store_id), int(offer.master_product_id)))


@event.listens_for(Session, "after_commit")
def _send_offer_pushes(session: Session) -> None:
    candidates = session.info.pop(_INFO_KEY, [])
    if not candidates:
        return
    # Keep collection requests fast: matching and Web Push happen outside the commit path.
    unique = list(set(candidates))
    thread = threading.Thread(target=_dispatch_candidates, args=(unique,), daemon=True)
    thread.start()


@event.listens_for(Session, "after_rollback")
def _drop_offer_pushes(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)
