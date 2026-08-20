from pathlib import Path
from types import SimpleNamespace

from app.models import Store
from app import web_collector
from app import prospects
from app.collection_quality import BenchmarkContext


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

    def collect(db, store_name, target_pdf, *, benchmark_context):
        calls.append(("collect", store_name, str(target_pdf), benchmark_context.value))
        return "parsed", "summary", "run"

    monkeypatch.setattr(web_collector, "_archive_downloaded_prospect", archive)
    monkeypatch.setattr(web_collector, "collect_pdf_for_store", collect)

    result = web_collector._collect_netto_from_official_prospect(object(), store, source)

    assert result == ("parsed", "summary", "run")
    assert calls[0][0] == "archive"
    assert calls[1][0] == "collect"
    assert calls[1][3] == "NOT_APPLICABLE"
    assert calls[0][2] == "https://example.test/prospect"
    assert calls[0][3] == "https://example.test/prospect.pdf"


def test_edeka_reuses_current_official_market_pdf_when_landing_page_is_unavailable(monkeypatch, tmp_path: Path):
    store = Store(
        id=7,
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Str. 35",
        external_id="071378",
        active=True,
        benchmark_verified=True,
    )
    source = SimpleNamespace(
        key="edeka_puderbach",
        url="https://www.edeka.de/maerkte/071378/angebote/",
    )
    pdf_path = tmp_path / "edeka-market.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    current = SimpleNamespace(
        pdf_url="https://media.smp-it-media.de/flyers/market/pdf?year=2026&week=34",
        local_path=str(pdf_path),
        valid_from=None,
        valid_to=None,
    )
    monkeypatch.setattr(prospects, "current_prospect", lambda db, target_store, period: current)
    monkeypatch.setattr(
        web_collector,
        "discover_official_pdf",
        lambda _url: (_ for _ in ()).throw(AssertionError("landing page must not be required for a current PDF")),
    )
    calls = []
    monkeypatch.setattr(
        web_collector,
        "_archive_downloaded_prospect",
        lambda db, target_store, **kwargs: calls.append(("archive", kwargs)),
    )
    monkeypatch.setattr(
        web_collector,
        "collect_pdf_for_store",
        lambda db, store_name, target, *, benchmark_context: calls.append(("collect", store_name, target, benchmark_context)) or ("parsed", "summary", "run"),
    )

    result = web_collector._collect_edeka_from_official_prospect(
        object(),
        store,
        source,
        BenchmarkContext.PRODUCTION,
    )

    assert result == ("parsed", "summary", "run")
    assert calls[0][0] == "archive"
    assert calls[0][1]["source_url"] == source.url
    assert calls[0][1]["pdf_url"] == current.pdf_url
    assert calls[1][2] == pdf_path
    assert calls[1][3] is BenchmarkContext.PRODUCTION


def test_edeka_discovers_and_downloads_pdf_for_new_market_without_store_specific_parser(monkeypatch, tmp_path: Path):
    store = Store(
        id=9,
        retailer="EDEKA",
        name="EDEKA Neuer Markt",
        postal_code="00000",
        city="Test",
        address="Test 1",
        active=True,
    )
    source = SimpleNamespace(key="auto_edeka_9", url="https://www.edeka.de/maerkte/999999/angebote/")
    pdf_path = tmp_path / "new-market.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    monkeypatch.setattr(prospects, "current_prospect", lambda db, target_store, period: None)
    monkeypatch.setattr(web_collector, "discover_official_pdf", lambda url: "https://media.example/new-market/pdf")
    monkeypatch.setattr(web_collector, "download_pdf", lambda url, target: pdf_path)
    monkeypatch.setattr(web_collector, "_archive_downloaded_prospect", lambda *args, **kwargs: None)
    monkeypatch.setattr(web_collector, "collect_pdf_for_store", lambda *args, **kwargs: ("parsed", "summary", "run"))

    assert web_collector._collect_edeka_from_official_prospect(object(), store, source) == ("parsed", "summary", "run")
