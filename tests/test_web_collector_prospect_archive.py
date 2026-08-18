from pathlib import Path
from types import SimpleNamespace

from app.models import Store
from app import web_collector


def test_netto_archives_downloaded_pdf_before_offer_import(monkeypatch, tmp_path: Path):
    store = Store(
        id=1,
        retailer="Netto Marken-Discount",
        name="Netto Test",
        postal_code="00000",
        city="Test",
        address="Test 1",
        external_id="6822",
        active=True,
        benchmark_verified=True,
    )
    source = SimpleNamespace(key="netto_test")
    pdf_path = tmp_path / "netto.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    calls = []

    monkeypatch.setattr(web_collector, "netto_weekly_prospect_url", lambda _store: "https://example.test/prospect")
    monkeypatch.setattr(web_collector, "discover_official_pdf", lambda _url: "https://example.test/prospect.pdf")
    monkeypatch.setattr(web_collector, "download_pdf", lambda _url, _target: pdf_path)

    def archive(db, target_store, *, source_url, pdf_url, pdf_path):
        calls.append(("archive", target_store.name, source_url, pdf_url, str(pdf_path)))

    def collect(db, store_name, target_pdf):
        calls.append(("collect", store_name, str(target_pdf)))
        return "parsed", "summary", "run"

    monkeypatch.setattr(web_collector, "_archive_downloaded_prospect", archive)
    monkeypatch.setattr(web_collector, "collect_pdf_for_store", collect)

    result = web_collector._collect_netto_from_official_prospect(object(), store, source)

    assert result == ("parsed", "summary", "run")
    assert calls[0][0] == "archive"
    assert calls[1][0] == "collect"
    assert calls[0][2] == "https://example.test/prospect"
    assert calls[0][3] == "https://example.test/prospect.pdf"
