from datetime import date
from types import SimpleNamespace

import app.collection_artifacts as artifacts


def _row(valid_from, valid_to):
    return SimpleNamespace(valid_from=valid_from, valid_to=valid_to)


def test_rewe_two_week_snapshot_keeps_persisted_archive_on_active_week(monkeypatch):
    monkeypatch.setattr(artifacts, "app_today", lambda: date(2026, 9, 15))
    current = _row("14.09.2026", "20.09.2026")
    nxt = _row("21.09.2026", "27.09.2026")
    result = {"offers": [current, nxt], "raw": b"<html></html>"}

    scoped = artifacts._rewe_archive_scope_result(result)

    assert scoped is not result
    assert scoped["offers"] == [current]
    assert scoped["raw"] == result["raw"]
    assert result["offers"] == [current, nxt]


def test_rewe_current_only_snapshot_keeps_existing_result(monkeypatch):
    monkeypatch.setattr(artifacts, "app_today", lambda: date(2026, 9, 15))
    current = _row("14.09.2026", "20.09.2026")
    result = {"offers": [current]}

    assert artifacts._rewe_archive_scope_result(result) is result


def test_rewe_provenance_view_covers_both_captured_cohorts_without_mutating_archive():
    archive = SimpleNamespace(
        id=7,
        pdf_bytes=b"%PDF-test",
        pdf_url="web-snapshot://captured-session/v3/1/2026-09-15",
        valid_from=date(2026, 9, 14),
        valid_to=date(2026, 9, 20),
        source_url="https://www.rewe.de/angebote/dierdorf/321019/test/",
        page_count=4,
    )
    result = {
        "offers": [
            _row("14.09.2026", "20.09.2026"),
            _row("21.09.2026", "27.09.2026"),
        ]
    }

    view = artifacts._rewe_provenance_archive_view(archive, result)

    assert view.id == archive.id
    assert view.valid_from == date(2026, 9, 14)
    assert view.valid_to == date(2026, 9, 27)
    assert archive.valid_from == date(2026, 9, 14)
    assert archive.valid_to == date(2026, 9, 20)
