from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from .config import settings
from .models import CollectionRun, Store


def _state_for_run(run: CollectionRun | None, stale_before: datetime) -> str:
    if not run:
        return "unknown"
    started = run.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if run.status == "failed":
        return "failed"
    if run.status == "no_offers":
        return "empty"
    if started < stale_before:
        return "stale"
    if run.status == "success":
        return "current"
    return run.status


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
        recent_runs = (
            db.query(CollectionRun)
            .filter(CollectionRun.store_id == store.id)
            .order_by(CollectionRun.started_at.desc())
            .limit(4)
            .all()
        )
        run = recent_runs[0] if recent_runs else None
        latest_web = next((r for r in recent_runs if (r.source_key or "").endswith(":web")), None)
        latest_pdf = next((r for r in recent_runs if (r.source_key or "").endswith(":pdf")), None)
        rows.append({
            "store": store,
            "run": run,
            "state": _state_for_run(run, stale_before),
            "web_run": latest_web,
            "pdf_run": latest_pdf,
        })
    return rows
