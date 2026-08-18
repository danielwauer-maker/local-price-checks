from datetime import date
import json

from app.engine_v140.browser_fetch import BrowserFetchResult
from app.engine_v140.lidl_flipbook import _extract_total_pages, _page_url
from app.engine_v140.lidl_live import _leaflets_from_html, _select_leaflet, collect_lidl_leaflet
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
        "data": {
            "offers": [{
                "productName": "Milch 1 l",
                "offerPrice": 0.99,
                "regularPrice": 1.19,
                "packageSize": "1 l",
                "promotion": True,
            }]
        },
    }]
    html = (
        "<html><body><h1>Aktionsprospekt</h1>"
        '<script id="lpc-network-json" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )

    def fake_browser_fetch(url):
        return BrowserFetchResult(
            content=html.encode("utf-8"),
            content_type="text/html; charset=utf-8",
            final_url=url,
            mode="playwright-test",
        )

    monkeypatch.setattr("app.engine_v140.lidl_live.browser_fetch", fake_browser_fetch)
    result = collect_lidl_leaflet(
        _source(),
        valid_from=date(2026, 8, 17),
        valid_to=date(2026, 8, 22),
    )
    assert result["fetch_mode"] == "playwright-test"
    assert len(result["offers"]) == 1
    offer = result["offers"][0]
    assert offer.product_name == "Milch 1 l"
    assert offer.price == 0.99
    assert offer.regular_price == 1.19
    assert offer.valid_from == "17.08.2026"
    assert offer.valid_to == "22.08.2026"
    assert offer.source_url.endswith("/current/ar/0")


def test_lidl_flipbook_builds_concrete_page_urls():
    url = "https://www.lidl.de/l/prospekte/demo/view/flyer/page/1?_ab=1&lf=HHZ"
    assert _page_url(url, 17) == "https://www.lidl.de/l/prospekte/demo/view/flyer/page/17?_ab=1&lf=HHZ"
    assert _page_url("https://www.lidl.de/l/prospekte/demo", 4).endswith("/view/flyer/page/4")


def test_lidl_flipbook_ignores_small_carousel_counters():
    assert _extract_total_pages("Bild 1 / 2 Seite 1 / 48 weitere Inhalte 2 / 3") == 48
    assert _extract_total_pages("Carousel 1 / 2") is None
