from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .extractor_adapter import ImportSummary, import_collected_offers
from .models import CollectionRun, Store
from .engine_v140.collectors import collect_one
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
    run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run.status = status
    run.offers_received = received
    run.offers_imported = imported
    run.message = message
    db.commit()


def _store_and_source(db: Session, store_name: str):
    store = db.query(Store).filter(Store.name == store_name).first()
    if not store:
        raise CollectionError(f"Unbekannter Markt: {store_name}")
    source = source_for_store(store.name)
    if not source:
        raise CollectionError(f"Keine Quelle registriert für: {store.name}")
    if source.retailer != store.retailer:
        raise CollectionError(f"Quellen-/Markt-Händler stimmen nicht überein: {store.name}")
    return store, source


def _summary_message(summary: ImportSummary) -> str:
    return (
        f"Importdiagnose: qualität={summary.rejected_quality}, "
        f"markt={summary.rejected_store}, datum={summary.rejected_date}, "
        f"online={summary.rejected_online}, neuProdukte={summary.created_products}, "
        f"neuAngebote={summary.created_offers}, aktualisiert={summary.updated_offers}"
    )


def collect_structured_for_store(db: Session, store_name: str):
    """Fetch the official source using the full 1.4 web collector and import it."""
    store, source = _store_and_source(db, store_name)
    run = _start_run(db, store, source.key + ":web")
    try:
        result = collect_one(source)
        rows = result.get("offers") or []
        summary = import_collected_offers(db, rows)
        status = "success" if summary.imported else "no_offers"
        fetch = f"fetch={result.get('fetch_mode','?')} final={result.get('final_url') or source.url}"
        message = f"{fetch} | {_summary_message(summary)}"
        _finish_run(db, run, status, len(rows), summary.imported, message[:1000])
        return result, summary, run
    except Exception as exc:
        db.rollback()
        run = db.get(CollectionRun, run.id)
        _finish_run(db, run, "failed", 0, 0, str(exc)[:1000])
        raise


def collect_pdf_for_store(db: Session, store_name: str, pdf_path: str | Path):
    """Parse one official/local prospect and import only validated local offers."""
    store, source = _store_and_source(db, store_name)
    run = _start_run(db, store, source.key + ":pdf")
    try:
        parsed: PdfParseResult = parse_pdf_file(source, pdf_path)
        summary: ImportSummary = import_collected_offers(db, parsed.rows)
        status = "success" if summary.imported else "no_offers"
        notes = " | ".join(parsed.notes[-3:]) if parsed.notes else ""
        message = f"{notes} | {_summary_message(summary)}".strip(" |")
        _finish_run(db, run, status, len(parsed.rows), summary.imported, message[:1000])
        return parsed, summary, run
    except Exception as exc:
        db.rollback()
        run = db.get(CollectionRun, run.id)
        _finish_run(db, run, "failed", 0, 0, str(exc)[:1000])
        raise


def latest_collection_runs(db: Session) -> dict[int, CollectionRun]:
    rows = db.query(CollectionRun).order_by(CollectionRun.started_at.desc()).all()
    latest: dict[int, CollectionRun] = {}
    for row in rows:
        latest.setdefault(row.store_id, row)
    return latest
