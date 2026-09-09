from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .clock import app_today
from .collection_quality import CollectionQualitySnapshot
from .data_operations_models import DailyCollectionRun, PriceObservation, SourceProduct
from .freshness import _state_for_run
from .market_activation import StoreActivationState
from .models import CollectionRun, MasterProduct, MediaAsset, Offer, Store
from .physical_market_identity import collapse_physical_stores


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _json(value: str | None, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def build_data_operations(db: Session, *, stale_after_hours: int = 36) -> dict:
    """Build the cockpit with a bounded set of batched queries."""
    now = datetime.now(timezone.utc)
    today = app_today()
    stores = collapse_physical_stores(
        db.query(Store).order_by(Store.retailer, Store.city, Store.name).all()
    )
    store_ids = [store.id for store in stores]
    runs = (
        db.query(CollectionRun)
        .filter(CollectionRun.store_id.in_(store_ids))
        .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
        .limit(max(200, len(store_ids) * 8))
        .all()
        if store_ids else []
    )
    runs_by_store: dict[int, list[CollectionRun]] = {}
    for run in runs:
        runs_by_store.setdefault(run.store_id, []).append(run)
    run_ids = [run.id for run in runs]
    snapshots = {
        row.run_id: row
        for row in (
            db.query(CollectionQualitySnapshot)
            .filter(CollectionQualitySnapshot.run_id.in_(run_ids)).all()
            if run_ids else []
        )
    }
    activations = {
        row.store_id: row
        for row in (
            db.query(StoreActivationState).filter(StoreActivationState.store_id.in_(store_ids)).all()
            if store_ids else []
        )
    }
    offer_aggregates = {
        store_id: (int(count), int(products), int(with_price))
        for store_id, count, products, with_price in (
            db.query(
                Offer.store_id,
                func.count(Offer.id),
                func.count(func.distinct(Offer.master_product_id)),
                func.sum(case((Offer.price > 0, 1), else_=0)),
            )
            .filter(
                Offer.store_id.in_(store_ids), Offer.local_store_offer.is_(True),
                Offer.valid_from <= today, Offer.valid_to >= today,
            )
            .group_by(Offer.store_id).all()
            if store_ids else []
        )
    }
    product_ids = [
        product_id for (product_id,) in
        db.query(Offer.master_product_id).filter(
            Offer.store_id.in_(store_ids), Offer.valid_from <= today, Offer.valid_to >= today,
        ).distinct().all()
    ] if store_ids else []
    imaged_products = {
        product_id for (product_id,) in (
            db.query(MediaAsset.master_product_id)
            .filter(
                MediaAsset.master_product_id.in_(product_ids),
                MediaAsset.kind == "product", MediaAsset.active.is_(True),
            ).distinct().all()
            if product_ids else []
        )
    }
    store_products = {store_id: set() for store_id in store_ids}
    if store_ids:
        for store_id, product_id in db.query(Offer.store_id, Offer.master_product_id).filter(
            Offer.store_id.in_(store_ids), Offer.valid_from <= today, Offer.valid_to >= today,
        ).distinct().all():
            store_products.setdefault(store_id, set()).add(product_id)

    market_rows = []
    attention = []
    stale_before = now - timedelta(hours=stale_after_hours)
    for store in stores:
        recent = runs_by_store.get(store.id, [])
        latest = recent[0] if recent else None
        successful = next((run for run in recent if run.status == "success"), None)
        successful_counts = [run.offers_imported for run in recent if run.status == "success" and run.offers_imported > 0][:5]
        baseline = float(median(successful_counts)) if successful_counts else None
        snapshot = snapshots.get(latest.id) if latest else None
        quality_metrics = _json(snapshot.metrics_json, {}) if snapshot else {}
        active_count, active_products, with_price = offer_aggregates.get(store.id, (0, 0, 0))
        image_count = len(store_products.get(store.id, set()) & imaged_products)
        image_pct = round(image_count / active_products * 100.0, 1) if active_products else 0.0
        price_pct = round(with_price / active_count * 100.0, 1) if active_count else 0.0
        state = _state_for_run(latest, stale_before)
        if latest and latest.status == "blocked":
            state = "blocked"
        if snapshot and snapshot.quality_status == "WARN" and state == "current":
            state = "warning"
        activation = activations.get(store.id)
        row = {
            "store": store, "activation": activation, "run": latest,
            "last_success": successful, "state": state, "offer_count": active_count,
            "baseline": baseline,
            "baseline_ratio": round(latest.offers_received / baseline * 100.0, 1) if latest and baseline else None,
            "match_pct": float(quality_metrics.get("import_rate", 0.0)),
            "image_pct": image_pct, "price_pct": price_pct,
            "quality": snapshot,
        }
        market_rows.append(row)
        if state in {"failed", "blocked", "warning", "stale", "empty", "unknown"}:
            severity = "critical" if state in {"failed", "blocked"} else "warning"
            reason = latest.message if latest and latest.message else {
                "stale": "Letzte erfolgreiche Sammlung ist veraltet.",
                "empty": "Der Collector lieferte keine Angebote.",
                "unknown": "Für diesen Markt liegt noch kein Collection Run vor.",
            }.get(state, "Qualitätsprüfung erforderlich.")
            attention.append({
                "severity": severity, "subject": f"{store.retailer} · {store.name}",
                "reason": reason, "timestamp": latest.started_at if latest else None,
                "url": f"/admin/collector#collector-runs", "label": "Collector öffnen",
            })
        for issue in quality_metrics.get("suspicious_names", [])[:5]:
            attention.append({
                "severity": "warning", "subject": issue.get("product_name", "Produkt"),
                "reason": f"Product Match/Name unsicher: {issue.get('reason', 'Prüfung erforderlich')}",
                "timestamp": latest.started_at if latest else None,
                "url": f"/admin/articles?edit={issue.get('product_id', '')}", "label": "Artikel prüfen",
            })
        if quality_metrics.get("price_anchors_unmatched"):
            attention.append({
                "severity": "critical", "subject": f"{store.retailer} · {store.name}",
                "reason": f"{quality_metrics['price_anchors_unmatched']} Preisanker ohne belastbares Produkt-Match.",
                "timestamp": latest.started_at if latest else None,
                "url": f"/admin/articles/prospect-audit?store_id={store.id}", "label": "Prospekt prüfen",
            })
        missing_prices = max(
            0,
            int(quality_metrics.get("eligible_offer_count", 0))
            - int(quality_metrics.get("offers_with_price", 0)),
        )
        if missing_prices or quality_metrics.get("quality_rejected") or quality_metrics.get("date_rejected"):
            reasons = []
            if missing_prices:
                reasons.append(f"{missing_prices} Preise fehlen")
            if quality_metrics.get("quality_rejected"):
                reasons.append(f"{quality_metrics['quality_rejected']} unplausible/ungültige Produkte oder Preise")
            if quality_metrics.get("date_rejected"):
                reasons.append(f"{quality_metrics['date_rejected']} Gültigkeitsprobleme")
            attention.append({
                "severity": "critical" if missing_prices else "warning",
                "subject": f"{store.retailer} · {store.name}", "reason": "; ".join(reasons) + ".",
                "timestamp": latest.started_at if latest else None,
                "url": f"/admin/articles/prospect-audit?store_id={store.id}", "label": "Fehler-Inbox öffnen",
            })
        if quality_metrics.get("duplicate_count"):
            attention.append({
                "severity": "warning", "subject": f"{store.retailer} · {store.name}",
                "reason": f"{quality_metrics['duplicate_count']} mögliche Duplicate Products/Offers.",
                "timestamp": latest.started_at if latest else None,
                "url": "/admin/articles", "label": "Artikel prüfen",
            })
        if active_products and image_pct < 80.0:
            attention.append({
                "severity": "warning", "subject": f"{store.retailer} · {store.name}",
                "reason": f"Bildabdeckung nur {image_pct:.1f}%.", "timestamp": latest.started_at if latest else None,
                "url": "/admin/media", "label": "Medien prüfen",
            })

    reference_conflicts = (
        db.query(
            PriceObservation.master_product_id,
            PriceObservation.store_id,
            func.count(func.distinct(PriceObservation.price)),
        )
        .filter(
            PriceObservation.price_type == "ADVERTISED_REFERENCE",
            PriceObservation.observed_at >= (now - timedelta(days=30)).replace(tzinfo=None),
        )
        .group_by(PriceObservation.master_product_id, PriceObservation.store_id)
        .having(func.count(func.distinct(PriceObservation.price)) > 1)
        .limit(50).all()
    )
    conflict_product_ids = [product_id for product_id, _store_id, _count in reference_conflicts]
    conflict_names = {
        row.id: row.name for row in (
            db.query(MasterProduct).filter(MasterProduct.id.in_(conflict_product_ids)).all()
            if conflict_product_ids else []
        )
    }
    stores_by_id = {store.id: store for store in stores}
    for product_id, store_id, count in reference_conflicts:
        store = stores_by_id.get(store_id)
        attention.append({
            "severity": "warning", "subject": conflict_names.get(product_id, f"Produkt {product_id}"),
            "reason": f"Reference Price Konflikt: {count} verschiedene beworbene Referenzwerte in 30 Tagen"
                      + (f" bei {store.name}." if store else "."),
            "timestamp": None, "url": f"/admin/articles?edit={product_id}", "label": "Provenance prüfen",
        })
    uncertain_matches = (
        db.query(SourceProduct)
        .filter(SourceProduct.match_confidence < 0.98)
        .order_by(SourceProduct.last_observed_at.desc())
        .limit(50).all()
    )
    for source_product in uncertain_matches:
        attention.append({
            "severity": "warning", "subject": source_product.source_name,
            "reason": f"Product Match unsicher ({source_product.match_confidence * 100:.1f}%).",
            "timestamp": source_product.last_observed_at,
            "url": f"/admin/articles?edit={source_product.master_product_id}", "label": "Match prüfen",
        })
    attention.sort(key=lambda item: (SEVERITY_ORDER[item["severity"]], item["timestamp"] or datetime.min))
    public_rows = [row for row in market_rows if row["store"].active and row["store"].benchmark_verified]
    active_offers = sum(row["offer_count"] for row in public_rows)
    public_products = sum(len(store_products.get(row["store"].id, set())) for row in public_rows)
    public_images = sum(
        len(store_products.get(row["store"].id, set()) & imaged_products) for row in public_rows
    )
    berlin_start = datetime.combine(today, datetime.min.time(), tzinfo=ZoneInfo("Europe/Berlin"))
    utc_start = berlin_start.astimezone(timezone.utc).replace(tzinfo=None)
    observations_today = db.query(func.count(PriceObservation.id)).filter(
        PriceObservation.observed_at >= utc_start
    ).scalar() or 0
    latest_daily = db.query(DailyCollectionRun).order_by(DailyCollectionRun.started_at.desc()).limit(20).all()
    return {
        "kpis": {
            "total": len(stores),
            "current": sum(1 for row in public_rows if row["state"] == "current"),
            "warning": sum(1 for row in public_rows if row["state"] in {"warning", "stale", "empty", "unknown"}),
            "blocked_failed": sum(1 for row in public_rows if row["state"] in {"blocked", "failed"}),
            "active_offers": active_offers,
            "observations_today": int(observations_today),
            "match_pct": round(sum(row["match_pct"] for row in public_rows) / len(public_rows), 1) if public_rows else 0.0,
            "image_pct": round(public_images / public_products * 100.0, 1) if public_products else 0.0,
            "open_reviews": len(attention),
        },
        "attention": attention,
        "markets": market_rows,
        "daily_runs": latest_daily,
    }
