from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from sqlalchemy.orm import Session

from .collection_quality import BenchmarkContext, persist_collection_quality
from .extractor_adapter import ImportSummary, import_collected_offers
from .models import CollectionRun, Store
from .product_media import persist_collected_product_images
from .engine_v140.collectors import collect_one
from .engine_v140.prospect_pdf_engine import PdfParseResult, parse_pdf_file
from .engine_v140.source_registry import RetailSource, source_for_store_record


class CollectionError(RuntimeError):
    pass


class CollectionArtifactHandler(Protocol):
    """Retailer adapter for artifacts produced by one collector result.

    Artifact creation runs after the official source has been fetched but before
    offer persistence. Finalization runs after import so provenance can link to
    the newly persisted offers. Failures do not discard valid raw offers, but
    they downgrade the collection run from ``success`` to ``warning``.
    """

    def archive_before_import(self, db: Session, store: Store, result: dict) -> str | None: ...

    def finalize_after_import(
        self,
        db: Session,
        store: Store,
        result: dict,
        summary: ImportSummary,
    ) -> str | None: ...


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
    db.refresh(run)
    if run.status == "failed" and "error_type=timeout" in (run.message or ""):
        # A watchdog may have closed a genuinely stuck collector from another
        # DB session. Never let the late worker rewrite that terminal timeout.
        return
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
    source = source_for_store_record(store)
    if not source:
        raise CollectionError(f"Keine Quelle registriert oder automatisch ableitbar für: {store.name}")
    if source.retailer != store.retailer:
        raise CollectionError(f"Quellen-/Markt-Händler stimmen nicht überein: {store.name}")
    return store, source


def _summary_message(summary: ImportSummary, images_saved: int = 0) -> str:
    return (
        f"Importdiagnose: qualität={summary.rejected_quality}, "
        f"markt={summary.rejected_store}, datum={summary.rejected_date}, "
        f"online={summary.rejected_online}, neuProdukte={summary.created_products}, "
        f"neuAngebote={summary.created_offers}, aktualisiert={summary.updated_offers}, "
        f"bilder={images_saved}"
    )


def _persist_images_best_effort(db: Session, rows) -> int:
    try:
        return persist_collected_product_images(db, rows)
    except Exception:
        db.rollback()
        return 0


def _record_collection_quality(
    db: Session,
    *,
    store: Store,
    run: CollectionRun,
    rows: list,
    summary: ImportSummary,
    images_saved: int,
    status: str,
    benchmark_context: BenchmarkContext | str,
) -> str:
    """Persist QA without conflating it with technical run health."""
    try:
        diagnostic, _metrics = persist_collection_quality(
            db,
            store=store,
            run=run,
            rows=rows,
            summary=summary,
            images_saved=images_saved,
            run_status=status,
            benchmark_context=benchmark_context,
        )
    except Exception as exc:
        db.rollback()
        return (
            f"run_status={status} quality_status=FAIL "
            f"benchmark_status=NOT_APPLICABLE qa_error={type(exc).__name__}: {exc}"
        )
    return diagnostic


def collect_structured_for_store(
    db: Session,
    store_name: str,
    source_override: RetailSource | None = None,
    collector_fn: Callable | None = None,
    before_import_fn: Callable | None = None,
    artifact_handler: CollectionArtifactHandler | None = None,
    benchmark_context: BenchmarkContext | str = BenchmarkContext.NOT_APPLICABLE,
    run_started_fn: Callable[[CollectionRun], None] | None = None,
):
    """Fetch one official source with the structured collector and import it.

    ``source_override`` and ``collector_fn`` support retailers such as Lidl
    where the public landing page first has to be resolved to the concrete
    current leaflet and rendered with Chromium. ``before_import_fn`` may archive
    an immutable audit artifact before rows are imported, so exact page
    provenance can be persisted during ``import_collected_offers``.

    ``artifact_handler`` is the production lifecycle for retailer-specific
    archives. Unlike the legacy runtime patch, it receives the exact successful
    collector result explicitly and can finalize provenance after import.
    """
    store, registered_source = _store_and_source(db, store_name)
    source = source_override or registered_source
    if source.retailer != store.retailer or source.store_name != store.name:
        raise CollectionError(f"Aufgelöste Quelle passt nicht zum Markt: {store.name}")
    if artifact_handler is None:
        from .collection_artifacts import artifact_handler_for

        artifact_handler = artifact_handler_for(store)

    run = _start_run(db, store, source.key + ":web")
    try:
        if run_started_fn:
            run_started_fn(run)
        result = (collector_fn or collect_one)(source)
        result["_artifact_managed"] = artifact_handler is not None
        artifact_diagnostics: list[str] = []
        artifact_failed = False
        if artifact_handler:
            try:
                diagnostic = artifact_handler.archive_before_import(db, store, result)
                if diagnostic:
                    artifact_diagnostics.append(diagnostic)
            except Exception as exc:
                db.rollback()
                artifact_failed = True
                artifact_diagnostics.append(
                    f"artifact_status=FAIL archive_created=false error={type(exc).__name__}: {exc}"
                )
        if before_import_fn:
            before_import_fn(result)
        db.refresh(run)
        if run.status != "running":
            raise CollectionError(
                f"Collector-Lauf wurde extern beendet: run_status={run.status} {run.message or ''}"
            )
        rows = result.get("offers") or []
        summary = import_collected_offers(db, rows)
        images_saved = _persist_images_best_effort(db, rows)
        if artifact_handler and not artifact_failed:
            try:
                diagnostic = artifact_handler.finalize_after_import(db, store, result, summary)
                if diagnostic:
                    artifact_diagnostics.append(diagnostic)
            except Exception as exc:
                db.rollback()
                artifact_failed = True
                artifact_diagnostics.append(
                    f"artifact_status=FAIL archive_created=true error={type(exc).__name__}: {exc}"
                )
        collector_warning = str(result.get("technical_warning") or "").strip()
        if artifact_failed or collector_warning:
            status = "warning" if summary.imported else "failed"
        else:
            status = "success" if summary.imported else "no_offers"

        quality_diagnostic = _record_collection_quality(
            db,
            store=store,
            run=run,
            rows=rows,
            summary=summary,
            images_saved=images_saved,
            status=status,
            benchmark_context=benchmark_context,
        )
        fetch = f"fetch={result.get('fetch_mode','?')} final={result.get('final_url') or source.url}"
        parts = [
            fetch,
            collector_warning,
            *artifact_diagnostics,
            quality_diagnostic,
            _summary_message(summary, images_saved),
        ]
        message = " | ".join(part for part in parts if part)
        _finish_run(db, run, status, len(rows), summary.imported, message[:1800])
        return result, summary, run
    except Exception as exc:
        db.rollback()
        run = db.get(CollectionRun, run.id)
        _finish_run(db, run, "failed", 0, 0, str(exc)[:1000])
        raise


def collect_pdf_for_store(
    db: Session,
    store_name: str,
    pdf_path: str | Path,
    *,
    benchmark_context: BenchmarkContext | str = BenchmarkContext.NOT_APPLICABLE,
):
    """Parse one official/local prospect and import only validated local offers."""
    store, source = _store_and_source(db, store_name)
    run = _start_run(db, store, source.key + ":pdf")
    try:
        parsed: PdfParseResult = parse_pdf_file(source, pdf_path)
        summary: ImportSummary = import_collected_offers(db, parsed.rows)
        images_saved = _persist_images_best_effort(db, parsed.rows)
        status = "success" if summary.imported else "no_offers"
        quality_diagnostic = _record_collection_quality(
            db,
            store=store,
            run=run,
            rows=list(parsed.rows),
            summary=summary,
            images_saved=images_saved,
            status=status,
            benchmark_context=benchmark_context,
        )
        notes = " | ".join(parsed.notes[-3:]) if parsed.notes else ""
        message = f"{notes} | {quality_diagnostic} | {_summary_message(summary, images_saved)}".strip(" |")
        _finish_run(db, run, status, len(parsed.rows), summary.imported, message[:1800])
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
