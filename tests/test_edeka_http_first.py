import httpx

from app.engine_v140 import browser_fetch as browser_fetch_module


def test_edeka_selected_market_offer_page_uses_http_first(monkeypatch):
    html = ("<html><body>" + ("Angebot: Himbeeren 1,79 € " * 400) + "</body></html>").encode()

    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, content=html, headers={"content-type": "text/html; charset=utf-8"})

    monkeypatch.setattr(browser_fetch_module.httpx, "get", fake_get)
    result = browser_fetch_module._edeka_http_first(
        "https://www.edeka.de/angebote/?selectedMarktID=071378", 45000
    )
    assert result is not None
    assert result.mode == "http-edeka-server-rendered"
    assert b"Himbeeren" in result.content


def test_edeka_market_detail_and_other_retailers_do_not_use_http_first(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("HTTP-first must not run for non-target URLs")

    monkeypatch.setattr(browser_fetch_module.httpx, "get", fail_get)
    assert browser_fetch_module._edeka_http_first(
        "https://www.edeka.de/maerkte/071378/angebote/", 45000
    ) is None
    assert browser_fetch_module._edeka_http_first(
        "https://www.penny.de/angebote", 45000
    ) is None


def test_edeka_http_first_falls_back_on_cdn_denial(monkeypatch):
    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(403, request=request, text="Access Denied")

    monkeypatch.setattr(browser_fetch_module.httpx, "get", fake_get)
    assert browser_fetch_module._edeka_http_first(
        "https://www.edeka.de/angebote/?selectedMarktID=071378", 45000
    ) is None
