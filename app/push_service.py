from __future__ import annotations

import base64
import json
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .push_models import PushSubscription
from .sharing_models import SharedShoppingList, SharedShoppingListMember

_VAPID_FILE = settings.data_dir / "vapid_private.pem"
_VAPID_LOCK = threading.Lock()
_BATCH_LOCK = threading.Lock()
_BATCHES: dict[tuple[int, int], dict] = {}
_BATCH_WINDOW_SECONDS = 8.0


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _ensure_vapid_private_key() -> Path:
    if _VAPID_FILE.exists():
        return _VAPID_FILE
    with _VAPID_LOCK:
        if _VAPID_FILE.exists():
            return _VAPID_FILE
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        _VAPID_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _VAPID_FILE.with_suffix(".tmp")
        tmp.write_bytes(pem)
        tmp.chmod(0o600)
        tmp.replace(_VAPID_FILE)
    return _VAPID_FILE


def vapid_public_key() -> str:
    private_path = _ensure_vapid_private_key()
    key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    public = key.public_key().public_numbers()
    raw = b"\x04" + public.x.to_bytes(32, "big") + public.y.to_bytes(32, "big")
    return _b64url(raw)


def _payload(title: str, body: str, url: str = "/liste", *, tag: str | None = None, data: dict | None = None) -> str:
    return json.dumps(
        {
            "title": title,
            "body": body,
            "url": url,
            "tag": tag or "spareno",
            "data": data or {},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def send_push_to_user(
    db: Session,
    user_id: int,
    *,
    title: str,
    body: str,
    url: str = "/liste",
    tag: str | None = None,
    data: dict | None = None,
    exclude_client_key: str | None = None,
    subscription_id: int | None = None,
) -> int:
    query = db.query(PushSubscription).filter(
        PushSubscription.user_id == user_id,
        PushSubscription.enabled.is_(True),
    )
    if subscription_id is not None:
        query = query.filter(PushSubscription.id == subscription_id)
    subscriptions = query.all()
    sent = 0
    private_key = str(_ensure_vapid_private_key())
    claims = {"sub": getattr(settings, "web_push_subject", "mailto:admin@spareno.app")}
    payload = _payload(title, body, url, tag=tag, data=data)
    for row in subscriptions:
        if exclude_client_key and row.client_key == exclude_client_key:
            continue
        try:
            webpush(
                subscription_info={
                    "endpoint": row.endpoint,
                    "keys": {"p256dh": row.p256dh, "auth": row.auth},
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=claims,
                timeout=8,
            )
            row.last_success_at = datetime.utcnow()
            row.last_error = None
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {404, 410}:
                row.enabled = False
            row.last_error = str(exc)[:1000]
        except Exception as exc:  # best-effort transport: never fail the product mutation
            row.last_error = str(exc)[:1000]
    db.commit()
    return sent


def _batch_body(list_name: str, counts: Counter[str]) -> tuple[str, str]:
    parts: list[str] = []
    added = counts.get("added", 0)
    completed = counts.get("completed", 0)
    reopened = counts.get("reopened", 0)
    if added:
        parts.append(f"{added} Artikel {'wurde' if added == 1 else 'wurden'} hinzugefügt")
    if completed:
        parts.append(f"{completed} Artikel {'wurde' if completed == 1 else 'wurden'} erledigt")
    if reopened:
        parts.append(f"{reopened} Artikel {'ist' if reopened == 1 else 'sind'} wieder offen")
    if not parts:
        parts.append("Die Einkaufsliste wurde aktualisiert")
    return f"{list_name} wurde aktualisiert", " · ".join(parts)


def _flush_batch(key: tuple[int, int]) -> None:
    with _BATCH_LOCK:
        batch = _BATCHES.pop(key, None)
    if not batch:
        return
    list_id, target_user_id = key
    db = SessionLocal()
    try:
        shopping_list = db.get(SharedShoppingList, list_id)
        if shopping_list is None:
            return
        if not db.query(SharedShoppingListMember).filter(
            SharedShoppingListMember.list_id == list_id,
            SharedShoppingListMember.user_id == target_user_id,
        ).first():
            return
        title, body = _batch_body(shopping_list.name, Counter(batch["counts"]))
        send_push_to_user(
            db,
            target_user_id,
            title=title,
            body=body,
            url="/liste",
            tag=f"shopping-list-{list_id}",
            data={"type": "shopping_list", "listId": str(list_id), "counts": dict(batch["counts"])},
        )
    finally:
        db.close()


def queue_shared_list_push(list_id: int, actor_user_id: int | None, action: str, count: int = 1) -> None:
    if actor_user_id is None or count <= 0:
        return
    db = SessionLocal()
    try:
        target_ids = [
            row.user_id
            for row in db.query(SharedShoppingListMember)
            .filter(SharedShoppingListMember.list_id == list_id)
            .all()
            if row.user_id != actor_user_id
        ]
    finally:
        db.close()
    for target_user_id in target_ids:
        key = (int(list_id), int(target_user_id))
        with _BATCH_LOCK:
            batch = _BATCHES.get(key)
            if batch is None:
                timer = threading.Timer(_BATCH_WINDOW_SECONDS, _flush_batch, args=(key,))
                timer.daemon = True
                batch = {"counts": Counter(), "timer": timer}
                _BATCHES[key] = batch
                timer.start()
            batch["counts"][action] += count
