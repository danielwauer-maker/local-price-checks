from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from .config import settings
from .collection_quality import BenchmarkContext
from .db import SessionLocal
from .edeka_discovery import collect_edeka_market_pdf
from .models import Store
from .web_collector import collect_store_from_web

_scheduler: BackgroundScheduler | None = None


def run_verified_market_collection() -> dict[str, str]:
    results: dict[str, str] = {}
    db = SessionLocal()
    try:
        stores = (
            db.query(Store)
            .filter(Store.active.is_(True), Store.benchmark_verified.is_(True))
            .order_by(Store.retailer, Store.name)
            .all()
        )
        for store in stores:
            try:
                if store.retailer == "EDEKA":
                    _, summary, run = collect_edeka_market_pdf(
                        db,
                        store,
                        benchmark_context=BenchmarkContext.PRODUCTION,
                    )
                else:
                    _, summary, run = collect_store_from_web(
                        db,
                        store.name,
                        benchmark_context=BenchmarkContext.PRODUCTION,
                    )
                results[store.name] = f"{run.status}:{summary.imported}"
            except Exception as exc:
                results[store.name] = f"failed:{type(exc).__name__}"
        return results
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if not settings.scheduler_enabled:
        return None
    if _scheduler and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="Europe/Berlin")
    _scheduler.add_job(
        run_verified_market_collection,
        trigger="cron",
        hour=settings.collection_hour,
        minute=settings.collection_minute,
        id="verified-market-collection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
