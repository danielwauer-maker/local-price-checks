from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_routes import _admin
from .clock import app_today
from .collection_quality import CollectionQualitySnapshot
from .config import settings
from .db import get_db
from .data_operations import build_data_operations
from .models import CollectionRun
from .production_readiness import (
    build_multi_market_readiness,
    next_week_offer_counts,
    next_week_window,
    quality_metric_for_display,
)

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


def _readiness_context(db: Session) -> dict:
    """Build the operator-facing seven-market production readiness view."""

    readiness = build_multi_market_readiness(db)
    today = app_today()
    next_start, next_end = next_week_window(today)
    next_counts = next_week_offer_counts(db, today=today)

    enriched_rows: list[dict] = []
    for row in readiness["stores"]:
        enriched = dict(row)
        store_id = row.get("store_id")
        metrics: dict = {}
        if store_id is not None:
            latest_run = (
                db.query(CollectionRun)
                .filter(CollectionRun.store_id == store_id)
                .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
                .first()
            )
            if latest_run is not None:
                snapshot = (
                    db.query(CollectionQualitySnapshot)
                    .filter(CollectionQualitySnapshot.run_id == latest_run.id)
                    .first()
                )
                if snapshot and snapshot.metrics_json:
                    try:
                        loaded = json.loads(snapshot.metrics_json)
                        if isinstance(loaded, dict):
                            metrics = loaded
                    except (TypeError, ValueError, json.JSONDecodeError):
                        metrics = {}

        enriched["next_week_offers"] = next_counts.get(store_id, 0) if store_id is not None else 0
        enriched["price_anchor_match_rate"] = quality_metric_for_display(
            metrics, "price_anchor_match_rate"
        )
        enriched["page_offer_recall"] = quality_metric_for_display(
            metrics, "page_offer_recall"
        )
        enriched_rows.append(enriched)

    return {
        **readiness,
        "stores": enriched_rows,
        "next_week_start": next_start,
        "next_week_end": next_end,
    }


@router.get("/admin/datenstatus")
def admin_data_status(request: Request, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    operations = build_data_operations(db, stale_after_hours=settings.stale_after_hours)
    return templates.TemplateResponse("admin_data_status.html", {
        "request": request,
        "actor": actor,
        "admin_section": "data_status",
        **operations,
        "scheduler_enabled": settings.scheduler_enabled,
        "stale_after_hours": settings.stale_after_hours,
    })


@router.get("/admin/collector/readiness")
def admin_production_readiness(
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    return templates.TemplateResponse(
        "admin_production_readiness.html",
        {
            "request": request,
            "actor": actor,
            "admin_section": "collector",
            **_readiness_context(db),
        },
    )
