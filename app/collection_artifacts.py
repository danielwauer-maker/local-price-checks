from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .extractor_adapter import ImportSummary
from .models import Store
from .prospect_models import ProspectArchive


@dataclass
class ReweCollectionArtifactHandler:
    """Archive the HTML already captured by the structured REWE collector."""

    archive_id: int | None = None
    page_count: int = 0

    def archive_before_import(self, db: Session, store: Store, result: dict) -> str:
        from .rewe_audit_runtime import archive_rewe_from_collector_result

        archive_rewe_from_collector_result(db, store, result)
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

        linked = int(_link_web_snapshot_provenance(db, store, archive) or 0)
        return f"artifact_status=PASS provenance_links={linked} offers_imported={summary.imported}"


def artifact_handler_for(store: Store):
    """Return the explicit artifact adapter for a retailer collection path."""
    if store.retailer == "REWE":
        return ReweCollectionArtifactHandler()
    return None
