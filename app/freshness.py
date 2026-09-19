from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from .config import settings
from .models import CollectionRun, Store
from .physical_market_identity import canonical_store_map, collapse_physical_stores


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


def state_for_run(run: CollectionRun | None, *, now: datetime | None = None) -> str:
    """Return the operational freshness state for one collector run."""
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    stale_before = reference - timedelta(hours=settings.stale_after_hours)
    return _state_for_run(run, stale_before)


def market_freshness(db: Session) -> list[dict]:
    now = datetime.now(timezone.utc)
    stores = db.query(Store).order_by(Store.retailer, Store.name).all()
    canonical_by_store_id = canonical_store_map(stores)
    physical_groups: dict[int, list[Store]] = {}
    canonical_by_id: dict[int, Store] = {}
    for store in stores:
        canonical = canonical_by_store_id[store.id]
        canonical_by_id[canonical.id] = canonical
        physical_groups.setdefault(canonical.id, []).append(store)

    rows = []
    for canonical_id, group in physical_groups.items():
        canonical = canonical_by_id[canonical_id]
        operational = [row for row in group if row.active and row.benchmark_verified]
        if not operational:
            continue
        store = canonical if canonical in operational else collapse_physical_stores(operational)[0]
        store_ids = [row.id for row in group]
        recent_runs = (
            db.query(CollectionRun)
            .filter(CollectionRun.store_id.in_(store_ids))
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
            "state": state_for_run(run, now=now),
            "web_run": latest_web,
            "pdf_run": latest_pdf,
        })
    return rows
