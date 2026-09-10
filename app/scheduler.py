from __future__ import annotations

from datetime import datetime, timezone
import json
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import func

from .config import settings
from .collection_quality import BenchmarkContext
from .collection_quality import CollectionQualitySnapshot
from .data_operations_models import DailyCollectionRun, PriceObservation
from .db import SessionLocal
from .edeka_live_collector import collect_edeka_web_for_store
from .models import Store
from .lokero_models import NormalPriceObservation
from .physical_market_identity import collapse_physical_stores
from .web_collector import collect_store_from_web

_scheduler: BackgroundScheduler | None = None


def run_verified_market_collection() -> dict[str, str]:
    results: dict[str, str] = {}
    db = SessionLocal()
    try:
        started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        berlin_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
        daily = db.query(DailyCollectionRun).filter_by(run_date=berlin_date).first()
        if daily is None:
            daily = DailyCollectionRun(run_date=berlin_date, started_at=started_at)
            db.add(daily)
        else:
            daily.started_at = started_at
            daily.finished_at = None
            daily.status = "running"
        db.commit()
        stores = collapse_physical_stores(
            db.query(Store)
            .filter(Store.active.is_(True), Store.benchmark_verified.is_(True))
            .order_by(Store.retailer, Store.name)
            .all()
        )
        daily.stores_planned = len(stores)
        run_ids: list[int] = []
        summaries = []
        store_outcomes: list[str] = []
        warnings: list[str] = []
        blockers: list[str] = []
        for store in stores:
            try:
                if store.retailer == "EDEKA":
                    _, summary, run = collect_edeka_web_for_store(
                        db,
                        store,
                        benchmark_context=BenchmarkContext.PRODUCTION,
                    )
                else:
                    result, summary, run = collect_store_from_web(
                        db,
                        store.name,
                        benchmark_context=BenchmarkContext.PRODUCTION,
                    )
                    if store.retailer == "REWE":
                        from .authoritative_offer_reconcile import reconcile_completed_rewe_collection

                        reconcile_completed_rewe_collection(db, store, result, summary, run)
                run_ids.append(run.id)
                summaries.append(summary)
                results[store.name] = f"{run.status}:{summary.imported}"
                if run.status == "blocked":
                    store_outcomes.append("blocked")
                    blockers.append(f"{store.name}: {run.message or 'collector blocked'}")
                elif run.status in {"success", "warning"}:
                    store_outcomes.append("succeeded")
                    if run.status == "warning":
                        warnings.append(f"{store.name}: {run.status} {run.message or ''}".strip())
                else:
                    store_outcomes.append("failed")
                    warnings.append(f"{store.name}: {run.status} {run.message or ''}".strip())
            except Exception as exc:
                results[store.name] = f"failed:{type(exc).__name__}"
                store_outcomes.append("failed")
                warnings.append(f"{store.name}: {type(exc).__name__}: {exc}")

        snapshots = (
            db.query(CollectionQualitySnapshot)
            .filter(CollectionQualitySnapshot.run_id.in_(run_ids)).all()
            if run_ids else []
        )
        metrics = [json.loads(row.metrics_json or "{}") for row in snapshots]
        observation_counts = dict(
            db.query(PriceObservation.price_type, func.count(PriceObservation.id))
            .filter(PriceObservation.collection_run_id.in_(run_ids))
            .group_by(PriceObservation.price_type).all()
        ) if run_ids else {}
        daily.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        daily.stores_succeeded = store_outcomes.count("succeeded")
        daily.stores_blocked = store_outcomes.count("blocked")
        daily.stores_failed = store_outcomes.count("failed")
        daily.offers_observed = sum(summary.imported for summary in summaries)
        daily.products_created = sum(summary.created_products for summary in summaries)
        daily.price_observations = sum(observation_counts.values())
        daily.reference_prices = int(observation_counts.get("ADVERTISED_REFERENCE", 0))
        daily.normal_price_observations = (
            db.query(func.count(NormalPriceObservation.id))
            .filter(
                NormalPriceObservation.observed_at >= started_at,
                NormalPriceObservation.observed_at <= daily.finished_at,
            ).scalar() or 0
        )
        daily.product_match_rate = round(
            sum(float(item.get("import_rate", 0.0)) for item in metrics) / len(metrics), 1
        ) if metrics else 0.0
        daily.image_coverage = round(
            sum(float(item.get("image_rate", 0.0)) for item in metrics) / len(metrics), 1
        ) if metrics else 0.0
        daily.price_coverage = round(
            sum(
                (float(item.get("offers_with_price", 0)) / float(item.get("eligible_offer_count", 1)) * 100.0)
                if item.get("eligible_offer_count") else 0.0
                for item in metrics
            ) / len(metrics), 1
        ) if metrics else 0.0
        daily.warnings_json = json.dumps(warnings, ensure_ascii=False)
        daily.blockers_json = json.dumps(blockers, ensure_ascii=False)
        daily.collection_run_ids_json = json.dumps(run_ids)
        if blockers:
            daily.status = "blocked"
        elif daily.stores_failed and not daily.stores_succeeded:
            daily.status = "failed"
        elif warnings or daily.stores_failed:
            daily.status = "warning"
        else:
            daily.status = "healthy"
        db.commit()
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
    if settings.scrape_health_email_enabled:
        # Import lazily so SMTP configuration has zero effect on installations
        # that do not opt into status e-mails.
        from .scrape_health_email import send_scrape_health_report

        _scheduler.add_job(
            send_scrape_health_report,
            trigger="cron",
            hour=settings.scrape_health_email_hour,
            minute=settings.scrape_health_email_minute,
            id="scrape-health-email",
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
