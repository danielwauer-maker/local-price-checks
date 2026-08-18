from datetime import date
import json

from app.engine_v140.browser_fetch import BrowserFetchResult
from app.engine_v140.lidl_flipbook import _extract_current_page, _extract_total_pages
from app.engine_v140.lidl_live import _leaflets_from_html, _select_leaflet, collect_lidl_leaflet
from app.engine_v140.lidl_manifest import manifest_offers, manifest_page_count
from app.engine_v140.source_registry import RetailSource


def _source(url: str = "https://www.lidl.de/l/prospekte/current/ar/0") -> RetailSource:
    return RetailSource(
        key="lidl_puderbach",
        retailer="Lidl",
        store_name="Lidl Puderbach",
        url=url,
        mode="leaflet_viewer",
        locality="store_specific",
        notes="test",
        supports_products=True,
        store_specific=True,
    )


def test_lidl_selects_leaflet_containing_target_date():
    html = """
    <a href="/l/prospekte/old/ar/0">Aktionsprospekt 10.08.2026 – 15.08.2026</a>
    <a href="/l/prospekte/current/ar/0">Aktionsprospekt 17.08.2026 – 22.08.2026</a>
    <a href="/l/prospekte/next/ar/0">Aktionsprospekt 24.08.2026 – 29.08.2026</a>
    """
    rows = _leaflets_from_html("https://www.lidl.de/c/online-prospekte/s10005610", html, store_context_confirmed=True)
    selected = _select_leaflet(rows, date(2026, 8, 18))
    assert selected.url == "https://www.lidl.de/l/prospekte/current/ar/0"
    assert selected.valid_from == date(2026, 8, 17)
    assert selected.valid_to == date(2026, 8, 22)
    assert selected.store_context_confirmed is True


def test_lidl_browser_network_offer_is_import_candidate(monkeypatch):
    payload = [{
        "url": "https://www.lidl.de/api/angebote",
        "data": {"offers": [{
            "productName": "Milch 1 l",
            "offerPrice": 0.99,
            "regularPrice": 1.19,
            "packageSize": "1 l",
            "promotion": True,
        }]},
    }]
    html = "<html><body><h1>Aktionsprospekt</h1>" + '<script id="lpc-network-json" type="application/json">' + json.dumps(payload) + "</script></body></html>"

    def fake_browser_fetch(url):
        return BrowserFetchResult(content=html.encode("utf-8"), content_type="text/html; charset=utf-8", final_url=url, mode="playwright-test")

    monkeypatch.setattr("app.engine_v140.lidl_live.browser_fetch", fake_browser_fetch)
    result = collect_lidl_leaflet(_source(), valid_from=date(2026, 8, 17), valid_to=date(2026, 8, 22))
    assert result["fetch_mode"] == "playwright-test"
    assert len(result["offers"]) == 1
    offer = result["offers"][0]
    assert offer.product_name == "Milch 1 l"
    assert offer.price == 0.99
    assert offer.regular_price == 1.19
    assert offer.valid_from == "17.08.2026"
    assert offer.valid_to == "22.08.2026"


def test_lidl_flipbook_ignores_small_carousel_counters():
    body = "Bild 1 / 2 Seite 7 / 48 weitere Inhalte 2 / 3"
    assert _extract_total_pages(body) == 48
    assert _extract_current_page(body) == 7
    assert _extract_total_pages("Carousel 1 / 2") is None
    assert _extract_current_page("Carousel 1 / 2") is None


def test_lidl_manifest_detects_logical_page_count():
    payloads = [{"url": "https://viewer.example/manifest", "data": {"publication": {"totalPages": 73, "pages": [{"pageNumber": i} for i in range(1, 74)]}}, "page_hint": 1}]
    assert manifest_page_count(payloads) == 73


def test_lidl_manifest_extracts_page_scoped_hotspot_offer():
    payloads = [{
        "url": "https://viewer.example/hotspots",
        "data": {"pages": [{"pageNumber": 12, "hotspots": [{"type": "product", "product": {
            "brandName": "Milbona", "productName": "Joghurt", "packageSize": "500 g",
            "offerPrice": {"value": "0,99"}, "regularPrice": 1.29, "gtin": "1234567890123",
        }}]}]},
        "page_hint": 10,
    }]
    rows = manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    assert len(rows) == 1
    row = rows[0]
    assert "Milbona" in row.product_name
    assert row.price == 0.99
    assert row.regular_price == 1.29
    assert row.source_text.startswith("PDF Seite 12:")


def test_lidl_global_manifest_page_list_overrides_request_page_hint():
    payloads = [{"url": "https://viewer.example/manifest", "page_hint": 1, "data": {"pages": [
        {"hotspots": [{"type": "product", "product": {"productName": "Artikel Seite Eins", "offerPrice": 1.11}}]},
        {"hotspots": [{"type": "product", "product": {"productName": "Artikel Seite Zwei", "offerPrice": 2.22}}]},
        {"hotspots": [{"type": "product", "product": {"productName": "Artikel Seite Drei", "offerPrice": 3.33}}]},
    ]}}]
    rows = manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    pages = {row.product_name: row.source_text.split(":", 1)[0] for row in rows}
    assert pages["Artikel Seite Eins"] == "PDF Seite 1"
    assert pages["Artikel Seite Zwei"] == "PDF Seite 2"
    assert pages["Artikel Seite Drei"] == "PDF Seite 3"


def test_lidl_global_product_catalogue_joins_hotspot_product_id_to_page():
    payloads = [
        {"url": "https://viewer.example/products", "page_hint": 1, "data": {"products": [{"productId": "100409050", "title": "LIVARNO Musselin-Bettwäsche, 155 x 220 cm", "brand": "LIVARNO", "price": "19.99"}]}},
        {"url": "https://viewer.example/hotspots", "page_hint": 1, "data": {"pages": [{"hotspots": []}, {"hotspots": [{"type": "product", "productId": "100409050"}]}]}},
    ]
    rows = manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    assert len(rows) == 1
    assert rows[0].source_text.startswith("PDF Seite 2:")


def test_lidl_recovers_page_reference_from_hotspot_product_url():
    payloads = [
        {"url": "https://viewer.example/products", "page_hint": 8, "data": {"products": [{"productId": "100777777", "title": "Milbona Fruchtjoghurt 500 g", "offerPrice": "0.99"}]}},
        {"url": "https://viewer.example/hotspots", "data": {"pages": [
            {"hotspots": [{"type": "product", "href": "https://viewer.example/product/p100777777"}]},
            {"hotspots": []},
            {"hotspots": []},
        ]}},
    ]
    rows = manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    assert len(rows) == 1
    assert rows[0].source_text.startswith("PDF Seite 1:")


def test_lidl_global_shop_catalogue_is_not_a_standalone_offer_source():
    payloads = [{"url": "https://viewer.example/page8", "data": {"pages": [{"pageNumber": 8, "products": [{
        "productId": "100409109", "title": "SILVERCREST Küchenmaschine", "price": "49.99",
        "canonicalUrl": "https://www.lidl.de/p/silvercrest-kuechenmaschine/p100409109",
    }]}]}}]
    rows = manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    assert rows == []


def test_lidl_global_catalogue_variants_do_not_become_standalone_offers():
    payloads = [{"url": "https://viewer.example/page8", "data": {"pages": [{"pageNumber": 8, "products": [
        {"productId": "1", "title": "SILVERCREST Küchenmaschine", "price": "49.99"},
        {"productId": "2", "title": "SILVERCREST Küchenmaschine digital Pastell", "price": "49.99"},
    ]}]}}]
    rows = manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    assert rows == []


def test_lidl_uvp_is_kept_on_page_scoped_hotspot_offer():
    payloads = [{"url": "https://viewer.example/page9", "data": {"pages": [{"pageNumber": 9, "hotspots": [{
        "type": "offer",
        "product": {"productId": "3", "title": "Parkside Werkzeug", "offerPrice": "19.99", "uvp": "49.99"},
    }]}]}}]
    rows = manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    assert len(rows) == 1
    assert rows[0].price == 19.99
    assert rows[0].regular_price == 49.99
