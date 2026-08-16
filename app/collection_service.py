from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from .extractor_adapter import ImportSummary, import_collected_offers
from .models import CollectionRun, Store
from .engine_v140.prospect_pdf_engine import PdfParseResult, parse_pdf_file
from .engine_v140.source_registry import source_for_store


class CollectionError(RuntimeError):
    pass


def _start_run(db: Session, store: Store, source_key: str) -> CollectionRun:
    run = CollectionRun(store_id=store.id, source_key=source_key, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finish_run(
    db: Session,
    run: CollectionRun,
    status: str,
    received: int = 0,
    imported: int = 0,
    message: str | None = None,
):
    run.finished_at = datetime.utcnow()
    run.status = status
    run.offers_received = received
    run.offers_imported = imported
    run.message = message
    db.commit()


def collect_pdf_for_store(db: Session, store_name: str, pdf_path: str | Path):
    """Parse one official/local prospect and import only validated local offers.

    This is the first production adapter around the benchmarked 1.4.0 engine.
    Network discovery is deliberately kept separate so a downloaded prospect can
    be benchmarked and imported through exactly the same parser path.
    """
    store = db.query(Store).filter(Store.name == store_name).first()
    if not store:
        raise CollectionError(f"Unbekannter Markt: {store_name}")
    source = source_for_store(store.name)
    if not source:
        raise CollectionError(f"Keine Quelle registriert für: {store.name}")
    if source.retailer != store.retailer:
        raise CollectionError(f"Quellen-/Markt-Händler stimmen nicht überein: {store.name}")

    run = _start_run(db, store, source.key)
    try:
        parsed: PdfParseResult = parse_pdf_file(source, pdf_path)
        summary: ImportSummary = import_collected_offers(db, parsed.rows)
        status = "success" if summary.imported else "no_offers"
        message = " | ".join(parsed.notes[-3:]) if parsed.notes else None
        _finish_run(db, run, status, len(parsed.rows), summary.imported, message)
        return parsed, summary, run
    except Exception as exc:
        db.rollback()
        run = db.get(CollectionRun, run.id)
        _finish_run(db, run, "failed", 0, 0, str(exc)[:1000])
        raise


def latest_collection_runs(db: Session) -> dict[int, CollectionRun]:
    """Latest collection result for each store, keyed by store_id."""
    rows = db.query(CollectionRun).order_by(CollectionRun.started_at.desc()).all()
    latest: dict[int, CollectionRun] = {}
    for row in rows:
        latest.setdefault(row.store_id, row)
    return latest
