from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.orm import Session

from .clock import app_today
from .extractor_adapter import ImportSummary
from .models import Store
from .prospect_models import ProspectArchive


def _offer_date(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _rewe_archive_scope_result(result: dict) -> dict:
    """Keep the canonical REWE archive period bound to the active week.

    A single snapshot may now contain a source-derived audit appendix for both
    current and next week. Collection QA historically binds the latest REWE
    archive to one exact offer period, so archive validity must remain the
    currently active cohort rather than become one artificial two-week range.
    """
    rows = list(result.get("offers") or [])
    today = app_today()
    active = []
    for row in rows:
        valid_from = _offer_date(getattr(row, "valid_from", None))
        valid_to = _offer_date(getattr(row, "valid_to", None))
        if valid_from and valid_to and valid_from <= today <= valid_to:
            active.append(row)
    if not active or len(active) == len(rows):
        return result
    scoped = dict(result)
    scoped["offers"] = active
    return scoped


def _rewe_provenance_archive_view(archive: ProspectArchive, result: dict):
    """Use a wider in-memory date view only while linking captured evidence.

    The persisted archive stays scoped to the current week for QA. The PDF can
    nevertheless contain the structured next-week audit appendix captured in
    the same official request, so provenance linking may safely inspect both
    exact offer cohorts without mutating the archive's persisted validity.
    """
    starts = []
    ends = []
    for row in result.get("offers") or []:
        valid_from = _offer_date(getattr(row, "valid_from", None))
        valid_to = _offer_date(getattr(row, "valid_to", None))
        if valid_from:
            starts.append(valid_from)
        if valid_to:
            ends.append(valid_to)
    if not starts or not ends:
        return archive
    return SimpleNamespace(
        id=archive.id,
        pdf_bytes=archive.pdf_bytes,
        pdf_url=archive.pdf_url,
        valid_from=min(starts),
        valid_to=max(ends),
        source_url=archive.source_url,
        page_count=archive.page_count,
    )


@dataclass
class ReweCollectionArtifactHandler:
    """Archive the HTML already captured by the structured REWE collector."""

    archive_id: int | None = None
    page_count: int = 0

    def archive_before_import(self, db: Session, store: Store, result: dict) -> str:
        from .rewe_audit_runtime import archive_rewe_from_collector_result

        archive_rewe_from_collector_result(db, store, _rewe_archive_scope_result(result))
        archive = (
            db.query(ProspectArchive)
            .filter(ProspectArchive.store_id == store.id)
            .order_by(ProspectArchive.fetched_at.desc(), ProspectArchive.id.desc())
            .first()
        )
        if archive is None:
            raise RuntimeError("REWE Snapshot wurde erzeugt, aber nicht als ProspectArchive gespeichert")
        self.archive_id = archive.id
        self.page_count = archive.page_count
        archive_count = db.query(ProspectArchive).filter(ProspectArchive.store_id == store.id).count()
        return (
            "source_type=web_snapshot archive_created=true "
            f"archive_count={archive_count} archive_pages={archive.page_count}"
        )

    def finalize_after_import(
        self,
        db: Session,
        store: Store,
        result: dict,
        summary: ImportSummary,
    ) -> str:
        if self.archive_id is None:
            raise RuntimeError("REWE ProspectArchive fehlt vor der Provenance-Verknüpfung")
        archive = db.get(ProspectArchive, self.archive_id)
        if archive is None:
            raise RuntimeError("REWE ProspectArchive wurde während des Imports entfernt")

        from .prospects import _link_web_snapshot_provenance

        provenance_view = _rewe_provenance_archive_view(archive, result)
        linked = int(_link_web_snapshot_provenance(db, store, provenance_view) or 0)
        return f"artifact_status=PASS provenance_links={linked} offers_imported={summary.imported}"


def artifact_handler_for(store: Store):
    """Return the explicit artifact adapter for a retailer collection path."""
    if store.retailer == "REWE":
        return ReweCollectionArtifactHandler()
    return None
