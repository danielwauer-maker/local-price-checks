from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic

from sqlalchemy.orm import Session

from .models import CollectionRun, CollectionRunProgress


def progress_diagnostic(row: CollectionRunProgress) -> str:
    values = [f"phase={row.phase}"]
    if row.error_type:
        values.append(f"error_type={row.error_type}")
    if row.pages_total is not None:
        values.append(f"pages_total={row.pages_total}")
    values.extend(
        (
            f"pages_structured={row.pages_structured}",
            f"pages_ocr={row.pages_ocr}",
            f"pages_done={row.pages_done}",
            f"assets_cached={row.assets_cached}",
            f"elapsed_seconds={row.elapsed_seconds:.1f}",
        )
    )
    return " ".join(values)


class CollectionProgressReporter:
    """Commit collector progress independently of the eventual run result."""

    def __init__(self, db: Session, run: CollectionRun):
        self.db = db
        self.run_id = run.id
        self.started = monotonic()

    def update(self, phase: str, **values) -> CollectionRunProgress:
        row = (
            self.db.query(CollectionRunProgress)
            .filter(CollectionRunProgress.run_id == self.run_id)
            .first()
        )
        if row is None:
            row = CollectionRunProgress(run_id=self.run_id)
            self.db.add(row)
        row.phase = phase
        for name in (
            "error_type", "pages_total", "pages_structured", "pages_ocr",
            "pages_done", "assets_cached",
        ):
            if name in values:
                setattr(row, name, values[name])
        row.elapsed_seconds = round(monotonic() - self.started, 1)
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run = self.db.get(CollectionRun, self.run_id)
        if run is not None and run.status == "running":
            run.message = progress_diagnostic(row)
        self.db.commit()
        return row
