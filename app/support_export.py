from __future__ import annotations

import csv
import hashlib
import io
import json
import platform
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from .clock import app_today
from .config import settings
from .models import CollectionRun, MasterProduct, Offer, Store
from .prospect_models import Prospect


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _write_json(zf: zipfile.ZipFile, name: str, payload) -> None:
    zf.writestr(name, json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


def _write_csv(zf: zipfile.ZipFile, name: str, headers: list[str], rows: list[list[object]]) -> None:
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(headers)
    writer.writerows(rows)
    zf.writestr(name, stream.getvalue())


def _file_info(path_text: str | None) -> dict:
    if not path_text:
        return {"exists": False}
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return {"path": str(path), "exists": False}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def build_support_export(db: Session) -> tuple[str, bytes]:
    """Create a compact support bundle without secrets or large prospect PDFs."""
    now = datetime.utcnow()
    today = app_today()
    stores = db.query(Store).order_by(Store.retailer, Store.name).all()
    runs = db.query(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(200).all()
    products = db.query(MasterProduct).order_by(MasterProduct.id).all()
    offers = (
        db.query(Offer)
        .filter(Offer.valid_from <= today, Offer.valid_to >= today)
        .order_by(Offer.store_id, Offer.master_product_id)
        .all()
    )
    prospects = db.query(Prospect).order_by(Prospect.store_id, Prospect.period_key).all()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _write_json(
            zf,
            "manifest.json",
            {
                "created_utc": now.isoformat() + "Z",
                "app_env": settings.app_env,
                "app_date": today.isoformat(),
                "python": platform.python_version(),
                "counts": {
                    "stores": len(stores),
                    "products": len(products),
                    "current_offers": len(offers),
                    "collection_runs_exported": len(runs),
                    "prospects": len(prospects),
                },
                "runtime": {
                    "scheduler_enabled": settings.scheduler_enabled,
                    "manual_collection_enabled": settings.manual_collection_enabled,
                    "collection_hour": settings.collection_hour,
                    "collection_minute": settings.collection_minute,
                    "collector_browser_enabled": settings.collector_browser_enabled,
                    "collector_timeout_seconds": settings.collector_timeout_seconds,
                    "stale_after_hours": settings.stale_after_hours,
                },
                "note": "Passwoerter/Secrets und Prospekt-PDF-Binaerdaten sind bewusst nicht enthalten.",
            },
        )
        _write_json(
            zf,
            "stores.json",
            [
                {
                    "id": s.id,
                    "retailer": s.retailer,
                    "name": s.name,
                    "address": s.address,
                    "postal_code": s.postal_code,
                    "city": s.city,
                    "active": s.active,
                    "benchmark_verified": s.benchmark_verified,
                    "external_id": s.external_id,
                    "source_url": s.source_url,
                }
                for s in stores
            ],
        )
        _write_json(
            zf,
            "collection_runs.json",
            [
                {
                    "id": r.id,
                    "store_id": r.store_id,
                    "store": r.store.name if r.store else None,
                    "source_key": r.source_key,
                    "started_at": r.started_at,
                    "finished_at": r.finished_at,
                    "status": r.status,
                    "offers_received": r.offers_received,
                    "offers_imported": r.offers_imported,
                    "message": r.message,
                }
                for r in runs
            ],
        )
        _write_json(
            zf,
            "prospects.json",
            [
                {
                    "id": p.id,
                    "store_id": p.store_id,
                    "store": p.store.name if p.store else None,
                    "period": p.period_key,
                    "valid_from": p.valid_from,
                    "valid_to": p.valid_to,
                    "source_url": p.source_url,
                    "pdf_url": p.pdf_url,
                    "page_count": p.page_count,
                    "active": p.active,
                    "fetched_at": p.fetched_at,
                    "local_file": _file_info(p.local_path),
                }
                for p in prospects
            ],
        )
        _write_csv(
            zf,
            "products.csv",
            ["id", "brand", "name", "package_size", "normalized_key"],
            [[p.id, p.brand or "", p.name, p.package_size or "", p.normalized_key] for p in products],
        )
        _write_csv(
            zf,
            "current_offers.csv",
            ["offer_id", "store_id", "store", "product_id", "product", "price", "unit_price", "unit", "valid_from", "valid_to", "source_url"],
            [
                [
                    o.id,
                    o.store_id,
                    o.store.name if o.store else "",
                    o.master_product_id,
                    o.product.name if o.product else "",
                    o.price,
                    o.unit_price if o.unit_price is not None else "",
                    o.unit_price_unit or "",
                    o.valid_from,
                    o.valid_to,
                    o.source_url or "",
                ]
                for o in offers
            ],
        )
        data_root = settings.data_dir / "prospects"
        listing = []
        if data_root.exists():
            for path in sorted(p for p in data_root.rglob("*") if p.is_file()):
                try:
                    listing.append({"path": str(path.relative_to(settings.data_dir)), "size_bytes": path.stat().st_size})
                except OSError:
                    pass
        _write_json(zf, "prospect_files.json", listing)

    filename = f"local_price_checks_support_quick_{now.strftime('%Y%m%d_%H%M%S')}.zip"
    return filename, buffer.getvalue()
