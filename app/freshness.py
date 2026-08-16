from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from .config import settings
from .models import CollectionRun, Store


def market_freshness(db: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(hours=settings.stale_after_hours)
    stores = (
        db.query(Store)
        .filter(Store.active.is_(True), Store.benchmark_verified.is_(True))
        .order_by(Store.retailer, Store.name)
        .all()
    )
    rows = []
    for store in stores:
        run = (
            db.query(CollectionRun)
            .filter(CollectionRun.store_id == store.id)
            .order_by(CollectionRun.started_at.desc())
            .first()
        )
        if not run:
            state = "unknown"
        else:
            started = run.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if run.status == "failed":
                state = "failed"
            elif started < stale_before:
                state = "stale"
            elif run.status in {"success", "no_offers"}:
                state = "current"
            else:
                state = run.status
        rows.append({"store": store, "run": run, "state": state})
    return rows
