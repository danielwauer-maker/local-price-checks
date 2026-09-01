from __future__ import annotations

from dataclasses import replace
from datetime import date
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.engine_v140.browser_fetch import BrowserFetchResult
from app.engine_v140.collectors import CollectedOffer
from app.models import Store
from app import web_offer_audit
from app.web_offer_audit import (
    AldiSuedWebOfferAdapter,
    EdekaWebOfferAdapter,
    NormaWebOfferAdapter,
    NettoWebOfferAdapter,
    PennyWebOfferAdapter,
    WebAuditError,
    WebAuditResult,
    WebOfferRecord,
    adapter_for,
    compare_regional_offer_sets,
    deduplicate,
    run_web_offer_audit,
    valid_product_image,
)
from app.web_offer_audit_models import WebOfferAuditItem, WebOfferAuditRun


def _store(retailer="PENNY", external_id="4030882"):
    return Store(
        id=7,
        retailer=retailer,
        name=f"{retailer} Testmarkt",
        postal_code="10115",
        city="Berlin",
        address="Testweg 1",
        external_id=external_id,
        source_url="https://www.penny.de/angebote",
        active=True,
    )


def _fetch(html: str, url="https://www.penny.de/angebote"):
    def fetcher(_url, timeout_ms):
        assert timeout_ms > 0
        return BrowserFetchResult(html.encode(), "text/html", url, "fixture")
    return fetcher


def _network_html(payloads) -> str:
    encoded = json.dumps(payloads, ensure_ascii=False).replace("</script>", "<\\/script>")
    return f'<html><body><script id="lpc-network-json" type="application/json">{encoded}</script></body></html>'


def test_penny_parses_sanitized_real_response_shape_and_excludes_permanent_category():
    current = {
        "url": "https://www.penny.de/.rest/offers/by-category/2026-36/obst-gemuese",
        "data": {"offerTiles": [{
            "id": "offer-1", "title": "Bio Äpfel", "quantity": "1 kg Schale", "price": "1,99 €",
            "listPrice": "2,49 €", "basePrice": "1 kg = 1,99 €", "validFrom": "2026-08-31",
            "validTo": "2026-09-05", "productData": {"uuid": "product-1", "ean": "4000000000012"},
            "images": [{"url": "https://img.penny.de/apple-400.jpg", "width": 400, "height": 400},
                       {"url": "https://img.penny.de/apple-1200.jpg", "width": 1200, "height": 1200}],
        }]},
    }
    permanent = {
        "url": "https://www.penny.de/.rest/offers/by-category/2026-36/dauerhaft-im-preis-gesenkt",
        "data": {"offerTiles": [{"id": "always", "title": "Dauerpreis", "price": "0,99 €"}]},
    }
    result = PennyWebOfferAdapter(fetcher=_fetch(_network_html([current, permanent]))).collect(_store(), "https://www.penny.de/angebote")
    assert result.raw_count == 1
    offer = result.offers[0]
    assert (offer.name, offer.price, offer.old_price) == ("Bio Äpfel", 1.99, 2.49)
    assert (offer.quantity_value, offer.quantity_unit) == (1.0, "kg")
    assert offer.external_product_id == "product-1"
    assert offer.ean == "4000000000012"
    assert offer.image_url.endswith("apple-1200.jpg")
    assert offer.valid_from == date(2026, 8, 31)


def test_penny_deduplicates_repeated_category_payloads_and_bounds_pages():
    row = {"id": "same", "title": "Joghurt 500 g", "price": 1.49}
    payloads = [
        {"url": f"https://www.penny.de/analytics/irrelevant-{index}", "data": {}}
        for index in range(50)
    ] + [
        {"url": f"https://www.penny.de/.rest/offers/by-category/2026-36/cat-{index}", "data": {"offerTiles": [row]}}
        for index in range(60)
    ]
    result = PennyWebOfferAdapter(fetcher=_fetch(_network_html(payloads)), max_pages=10).collect(_store(), "https://www.penny.de/angebote")
    assert result.raw_count == 10
    assert len(result.offers) == 1
    assert result.duplicate_count == 9


def test_penny_separates_current_and_next_iso_week():
    payloads = [
        {"url": "https://www.penny.de/.rest/offers/by-category/2026-36/molkerei", "data": {"offerTiles": [{"id": "current", "title": "Aktuelle Milch", "price": "1,19 €"}]}},
        {"url": "https://www.penny.de/.rest/offers/by-category/2026-37/molkerei", "data": {"offerTiles": [{"id": "next", "title": "Nächste Milch", "price": "1,09 €"}]}},
    ]
    html = _network_html(payloads)
    adapter = PennyWebOfferAdapter(fetcher=_fetch(html))
    assert [row.name for row in adapter.collect(_store(), "https://www.penny.de/angebote", "current").offers] == ["Aktuelle Milch"]
    assert [row.name for row in adapter.collect(_store(), "https://www.penny.de/angebote", "next").offers] == ["Nächste Milch"]


def test_aldi_requires_service_point_and_parses_product_search_shape():
    with pytest.raises(WebAuditError) as missing:
        AldiSuedWebOfferAdapter(fetcher=_fetch("<html/>", "https://www.aldi-sued.de/angebote" )).collect(_store("ALDI SÜD", external_id=None), "https://www.aldi-sued.de/angebote")
    assert missing.value.error_type == "browser_required"

    payload = [{
        "url": "https://api.aldi-sued.de/v3/product-search?servicePoint=B384&offset=0&limit=12",
        "data": {"meta": {"pagination": {"totalCount": 1}}, "data": [{
            "sku": "000000000000229496", "name": "Bio Milch", "brand": "Milsani",
            "sellingSize": "1 l", "price": 95,
            "assets": [{"url": "https://api.aldi-sued.de/product/milk.webp", "width": 800, "height": 800}],
        }]},
    }]
    result = AldiSuedWebOfferAdapter(fetcher=_fetch(_network_html(payload), "https://www.aldi-sued.de/angebote")).collect(_store("ALDI SÜD", "B384"), "https://www.aldi-sued.de/angebote")
    assert result.offers[0].external_product_id == "000000000000229496"
    assert result.offers[0].price == 0.95
    with pytest.raises(WebAuditError) as future:
        AldiSuedWebOfferAdapter(fetcher=_fetch(_network_html(payload), "https://www.aldi-sued.de/angebote")).collect(
            _store("ALDI SÜD", "B384"), "https://www.aldi-sued.de/angebote", "next"
        )
    assert future.value.error_type == "endpoint_changed"


def test_aldi_paginates_until_total_and_stops_at_last_offset():
    first = [{
        "url": "https://api.aldi-sued.de/v3/product-search?servicePoint=B384&offset=0&limit=2",
        "data": {"meta": {"pagination": {"totalCount": 5}}, "data": [
            {"sku": "1", "name": "Artikel Eins", "price": 100},
            {"sku": "2", "name": "Artikel Zwei", "price": 200},
        ]},
    }]
    calls = []
    def page_fetcher(url):
        calls.append(url)
        offset = 2 if "offset=2" in url else 4
        rows = [
            {"sku": str(offset + index + 1), "name": f"Artikel {offset + index + 1}", "price": 100 + offset + index}
            for index in range(min(2, 5 - offset))
        ]
        return {"meta": {"pagination": {"totalCount": 5}}, "data": rows}
    result = AldiSuedWebOfferAdapter(
        fetcher=_fetch(_network_html(first), "https://www.aldi-sued.de/angebote"), page_fetcher=page_fetcher, max_pages=4
    ).collect(_store("ALDI SÜD", "B384"), "https://www.aldi-sued.de/angebote")
    assert len(result.offers) == 5
    assert len(calls) == 2
    assert "offset=2" in calls[0]
    assert "offset=4" in calls[1]


@pytest.mark.parametrize("adapter_cls,html,expected", [
    (EdekaWebOfferAdapter, '<main><p>Gültig ab 31.08.2026, alle Angebote bis 05.09.2026</p><article><h2><a href="#angebot-offer-uuid"><span>Angebot:</span> Marken Butter</a></h2><span>2.49</span><span class="sr-only">Festpreis von 2.49€</span><img src="https://offer-images.api.edeka/butter.webp" alt=""></article></main>', "Marken Butter"),
    (NormaWebOfferAdapter, '<article id="of_123"><strong class="supplier">Bellaro</strong><h3>Röstkaffee 500 g</h3><span>statt 6,99 € nur 4,99 €</span><img data-src="https://www.norma-online.de/images/coffee.jpg" alt="Nur gültig vom 31.08. bis 06.09.2026"></article>', "Röstkaffee 500 g"),
])
def test_semantic_html_adapters_parse_offer_cards(adapter_cls, html, expected):
    retailer = "EDEKA" if adapter_cls is EdekaWebOfferAdapter else "NORMA"
    official_url = "https://www.edeka.de/maerkte/071378/angebote/" if retailer == "EDEKA" else "https://www.norma-online.de/de/angebote/ab-montag,-31.08.26/"
    result = adapter_cls(fetcher=_fetch(html, official_url)).collect(_store(retailer), official_url)
    assert result.offers[0].name == expected
    assert result.offers[0].price == (2.49 if retailer == "EDEKA" else 4.99)
    if retailer == "EDEKA":
        assert result.offers[0].external_offer_id == "angebot-offer-uuid"
        assert result.offers[0].valid_from == date(2026, 8, 31)
        assert result.offers[0].valid_to == date(2026, 9, 5)
    else:
        assert result.offers[0].brand == "Bellaro"
        assert result.offers[0].valid_from == date(2026, 8, 31)
        assert result.offers[0].valid_to == date(2026, 9, 6)


def test_invalid_json_captcha_timeout_and_empty_are_explicit():
    cases = [
        (_fetch('<script id="lpc-network-json">{bad</script>'), "invalid_json"),
        (_fetch("<html><body>Complete the CAPTCHA</body></html>"), "captcha"),
        (_fetch("<html><body>No offer surface</body></html>"), "empty"),
    ]
    for fetcher, expected in cases:
        with pytest.raises(WebAuditError) as failure:
            PennyWebOfferAdapter(fetcher=fetcher).collect(_store(), "https://www.penny.de/angebote")
        assert failure.value.error_type == expected

    def timeout(_url, timeout_ms):
        raise TimeoutError("page timeout")
    with pytest.raises(WebAuditError) as failure:
        PennyWebOfferAdapter(fetcher=timeout).collect(_store(), "https://www.penny.de/angebote")
    assert failure.value.error_type == "timeout"

    with pytest.raises(WebAuditError) as failure:
        PennyWebOfferAdapter(fetcher=_fetch("<html/>" )).collect(_store(), "https://internal.invalid/admin")
    assert failure.value.error_type == "blocked"


def test_offer_validation_image_filter_and_deduplication():
    assert valid_product_image("https://cdn.example/product-large.webp")
    assert not valid_product_image("https://cdn.example/logo.png")
    first = WebOfferRecord("PENNY", 1, "https://penny.de", "Cola 1 l", external_offer_id="x", price=1.0, image_url="https://cdn.example/logo.png")
    second = WebOfferRecord("PENNY", 1, "https://penny.de", "Cola 1 l", external_offer_id="x", price=1.0, image_url="https://cdn.example/cola.jpg")
    rows, duplicate_count = deduplicate([first, second])
    assert duplicate_count == 1
    assert rows[0].image_url.endswith("cola.jpg")


def test_regional_comparison_reports_identical_and_additional_offers():
    shared_left = WebOfferRecord("PENNY", 1, "https://www.penny.de", "Milch", external_product_id="milk", price=1.19)
    shared_right = WebOfferRecord("PENNY", 2, "https://www.penny.de", "Milch", external_product_id="milk", price=1.29)
    regional = WebOfferRecord("PENNY", 2, "https://www.penny.de", "Regional", external_product_id="regional", price=2.0)
    identical = compare_regional_offer_sets([shared_left], [replace(shared_left, store_id=2)])
    assert identical["jaccard"] == 1.0
    assert identical["price_differences"] == 0
    mixed = compare_regional_offer_sets([shared_left], [shared_right, regional])
    assert mixed["shared"] == 1
    assert mixed["right_only"] == 1
    assert mixed["price_differences"] == 1


def test_norma_keeps_explicit_integer_price_and_missing_price_as_audit_evidence():
    html = '''<main>
      <article id="of_1"><strong class="supplier">Feinkost</strong><h3>Balsamico 250 ml</h3><span>1 l = 8,– 2,–* Filiale</span></article>
      <article id="of_2"><strong class="supplier">Kinder</strong><h3>Kinder-Produkte</h3><span>20% billiger</span></article>
      <article><h3>Newsletter</h3></article>
    </main>'''
    url = "https://www.norma-online.de/de/angebote/ab-montag,-31.08.26/"
    result = NormaWebOfferAdapter(fetcher=_fetch(html, url)).collect(_store("NORMA"), url)
    assert result.raw_count == 2
    assert result.offers[0].price == 2.0
    assert result.offers[0].valid_from == date(2026, 8, 31)
    assert result.offers[1].price is None
    assert result.offers[1].valid is False
    assert "missing_price" in result.offers[1].validation_errors


def test_norma_discovers_next_week_url_dynamically_from_navigation():
    current_url = "https://www.norma-online.de/de/angebote/ab-montag,-31.08.26/"
    next_url = "https://www.norma-online.de/de/angebote/ab-montag,-07.09.26/"
    current_html = f'''<nav><a href="{next_url}">Nächste Woche</a></nav>
      <article id="of_current"><strong class="supplier">Heute</strong><h3>Aktuell</h3><span>1,99 €</span></article>'''
    next_html = '<article id="of_next"><strong class="supplier">Morgen</strong><h3>Nächste Woche</h3><span>2,49 €</span></article>'
    def fetcher(url, timeout_ms, **_kwargs):
        html = next_html if url == next_url else current_html
        return BrowserFetchResult(html.encode(), "text/html", url, "fixture")
    result = NormaWebOfferAdapter(fetcher=fetcher).collect(_store("NORMA"), current_url, "next")
    assert [row.name for row in result.offers] == ["Nächste Woche"]
    assert result.offers[0].valid_from == date(2026, 9, 7)
    assert "dynamisch" in (result.message or "")


def test_adapter_registry_contains_all_six_retailers():
    assert {type(adapter_for(name)).__name__ for name in ["REWE", "Netto Marken-Discount", "EDEKA", "PENNY", "ALDI SÜD", "NORMA"]} == {
        "ReweWebOfferAdapter", "NettoWebOfferAdapter", "EdekaWebOfferAdapter", "PennyWebOfferAdapter", "AldiSuedWebOfferAdapter", "NormaWebOfferAdapter"
    }


def test_netto_rejects_persisted_browser_context_for_another_store(monkeypatch):
    calls = []
    row = CollectedOffer(
        "audit", "Netto Dierdorf", "Netto Marken-Discount", "Butter 250 g", "Molkerei", 1.99,
        quantity=250, unit="g", source_url="https://www.netto-online.de/filialangebote",
    )
    def collector(source):
        calls.append(source.url)
        return {
            "offers": [row], "raw": b'<div class="your-store__box selected">Netto Filiale Klenzestrasse 50 80469 Muenchen</div>',
            "final_url": source.url, "fetch_mode": "fixture", "content_type": "text/html",
        }
    monkeypatch.setattr(web_offer_audit, "collect_one", collector)
    store = Store(
        id=8, retailer="Netto Marken-Discount", name="Netto Dierdorf", postal_code="56269",
        city="Dierdorf", address="Koenigsberger Str. 1", external_id="6822", active=True,
    )
    with pytest.raises(WebAuditError) as failure:
        NettoWebOfferAdapter().collect(store, "https://www.netto-online.de/filialangebote")
    assert failure.value.error_type == "browser_required"
    assert len(calls) == 1


def test_run_persists_only_audit_tables_and_artifact(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'audit.sqlite'}", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    db = TestSession()
    store = Store(retailer="PENNY", name="PENNY Berlin", postal_code="10115", city="Berlin", address="Test 1", external_id="4030882", source_url="https://www.penny.de/angebote", active=True)
    db.add(store)
    db.commit()
    db.refresh(store)

    class FakeAdapter:
        collector_path = "fixture"
        def collect(self, target, url, period_key):
            row = WebOfferRecord(target.retailer, target.id, url, "Testmilch 1 l", price=1.29, quantity="1 l", quantity_value=1, quantity_unit="l")
            row.validate()
            return WebAuditResult([row], url, url, self.collector_path, 1)

    monkeypatch.setattr(web_offer_audit, "adapter_for", lambda _retailer: FakeAdapter())
    monkeypatch.setattr(web_offer_audit, "settings", replace(web_offer_audit.settings, data_dir=tmp_path))
    run = run_web_offer_audit(db, store)
    assert run.status == "success"
    assert db.query(WebOfferAuditRun).count() == 1
    assert db.query(WebOfferAuditItem).count() == 1
    assert run.offers[0].name == "Testmilch 1 l"
    assert (tmp_path / "diagnostics" / "web_offer_audit" / str(store.id)).exists()
    db.close()


def test_failed_run_artifacts_include_bounded_html_json_console_requests_and_screenshot(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'failed.sqlite'}", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    db = TestSession()
    store = Store(retailer="PENNY", name="PENNY Fehler", postal_code="10115", city="Berlin", address="Test 2", external_id="4030882", source_url="https://www.penny.de/angebote", active=True)
    db.add(store)
    db.commit()
    db.refresh(store)

    class FailedAdapter:
        collector_path = "fixture_failure"
        def collect(self, target, url, period_key):
            raise WebAuditError("captcha", "CAPTCHA", {
                "html": "<html><body>CAPTCHA</body></html>",
                "html_sha256": "abc", "response_bytes": 34, "content_type": "text/html", "fetch_mode": "fixture",
                "network_payloads": [{"url": "https://www.penny.de/.rest/offers", "data": {"error": "captcha"}}],
                "console_errors": ["blocked script"], "failed_requests": ["GET /offers :: blocked"],
                "screenshot_png": b"\x89PNG\r\n\x1a\nfixture",
            })

    monkeypatch.setattr(web_offer_audit, "adapter_for", lambda _retailer: FailedAdapter())
    monkeypatch.setattr(web_offer_audit, "settings", replace(web_offer_audit.settings, data_dir=tmp_path))
    run = run_web_offer_audit(db, store)
    assert (run.status, run.error_type) == ("failed", "captcha")
    artifact_dir = tmp_path / "diagnostics" / "web_offer_audit" / str(store.id)
    manifest = next(path for path in artifact_dir.glob("run-*.json") if not path.name.endswith(".network.json"))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["raw_response_metadata"]["console_errors"] == ["blocked script"]
    assert manifest.with_suffix(".html").exists()
    assert json.loads(manifest.with_suffix(".network.json").read_text(encoding="utf-8"))[0]["data"]["error"] == "captcha"
    assert manifest.with_suffix(".png").read_bytes().startswith(b"\x89PNG")
    db.close()
