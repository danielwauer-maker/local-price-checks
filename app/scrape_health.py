from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import CollectionRun, Store
from .physical_market_identity import collapse_physical_stores
from .retailer_capabilities import rollout_enabled


@dataclass(frozen=True)
class ScrapeHealth:
    store_id: int
    store_name: str
    retailer: str
    state: str
    latest_run_status: str | None
    latest_run_at: datetime | None
    action: str


def scrape_health_rows(db: Session, *, stale_after_hours: int = 36) -> list[ScrapeHealth]:
    now = datetime.utcnow()
    threshold = now - timedelta(hours=stale_after_hours)
    stores = collapse_physical_stores(db.query(Store).order_by(Store.retailer, Store.city, Store.name).all())
    result: list[ScrapeHealth] = []
    for store in stores:
        if not rollout_enabled(store.retailer):
            result.append(ScrapeHealth(
                store.id, store.name, store.retailer, "waiting", None, None,
                "Retailer-Collector noch nicht für Rollout freigegeben.",
            ))
            continue
        run = (
            db.query(CollectionRun)
            .filter(CollectionRun.store_id == store.id)
            .order_by(CollectionRun.started_at.desc())
            .first()
        )
        if run is None:
            state = "needs_test"
            action = "Test-Scrape durchführen."
        elif run.status in {"failed", "no_offers"}:
            state = "manual_required"
            action = "Collector prüfen; vor Veröffentlichung keinen Gate-Fortschritt zulassen."
        elif run.started_at < threshold:
            state = "stale"
            action = "Scrape erneut ausführen und Aktualität bestätigen."
        elif run.status == "warning":
            state = "warning"
            action = "Warnung/Qualitätsdiagnose prüfen."
        else:
            state = "healthy"
            action = "Kein Eingriff erforderlich."
        result.append(ScrapeHealth(
            store.id,
            store.name,
            store.retailer,
            state,
            run.status if run else None,
            run.started_at if run else None,
            action,
        ))
    return result


def scrape_health_summary(db: Session) -> dict[str, int]:
    rows = scrape_health_rows(db)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.state] = counts.get(row.state, 0) + 1
    return counts
