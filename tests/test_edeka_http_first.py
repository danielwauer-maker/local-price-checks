import httpx
import pytest

from app.engine_v140 import browser_fetch as browser_fetch_module
from app.engine_v140.browser_fetch import (
    BrowserFetchError,
    _approved_edeka_navigation,
    _safe_diagnostic_url,
)


def test_edeka_selected_market_offer_page_uses_http_first(monkeypatch):
    html = ("<html><body>" + ("Angebot: Himbeeren 1,79 € " * 400) + "</body></html>").encode()

    def fake_get(url, **kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["headers"]["User-Agent"] == "Spareno-Audit/1.0"
        assert "Mozilla" not in kwargs["headers"]["User-Agent"]
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, content=html, headers={"content-type": "text/html; charset=utf-8"})

    monkeypatch.setattr(browser_fetch_module.httpx, "get", fake_get)
    result = browser_fetch_module._edeka_http_first(
        "https://www.edeka.de/angebote/?selectedMarktID=071378", 45000
    )
    assert result is not None
    assert result.mode == "http-edeka-server-rendered"
    assert b"Himbeeren" in result.content
    assert result.diagnostics["http_status"] == 200
    assert result.diagnostics["final_host"] == "www.edeka.de"
    assert result.diagnostics["fallback_used"] is False
    assert "set-cookie" not in result.diagnostics["response_headers"]


def test_edeka_market_detail_uses_http_first_but_other_retailers_do_not(monkeypatch):
    html = ("<html><body>" + ("Angebot: Himbeeren 1,79 € " * 400) + "</body></html>").encode()

    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, content=html, headers={"content-type": "text/html"})

    monkeypatch.setattr(browser_fetch_module.httpx, "get", fake_get)
    assert browser_fetch_module._edeka_http_first(
        "https://www.edeka.de/maerkte/071378/angebote/", 45000
    ) is not None

    def fail_get(*args, **kwargs):
        raise AssertionError("HTTP-first must not run for non-target URLs")

    monkeypatch.setattr(browser_fetch_module.httpx, "get", fail_get)
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


def test_edeka_http_first_records_sanitized_akamai_denial(monkeypatch):
    attempts = []

    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(
            403, request=request, text="Access Denied", headers={
                "server": "AkamaiGHost", "content-type": "text/html", "set-cookie": "secret=value",
            },
        )

    monkeypatch.setattr(browser_fetch_module.httpx, "get", fake_get)
    assert browser_fetch_module._edeka_http_first(
        "https://www.edeka.de/maerkte/071378/angebote/", 45000, attempts=attempts
    ) is None
    assert attempts[0]["http_status"] == 403
    assert attempts[0]["body_marker"] == "akamai_access_denied"
    assert attempts[0]["response_bytes"] == len(b"Access Denied")
    assert "set-cookie" not in attempts[0]["response_headers"]


def test_edeka_http_first_allows_only_official_https_redirects(monkeypatch):
    html = ("<html><body>" + ("Angebot: Himbeeren 1,79 € " * 400) + "</body></html>").encode()
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        request = httpx.Request("GET", url)
        if len(requested) == 1:
            return httpx.Response(302, request=request, headers={"location": "https://edeka.de/maerkte/071378/angebote/"})
        return httpx.Response(200, request=request, content=html, headers={"content-type": "text/html"})

    monkeypatch.setattr(browser_fetch_module.httpx, "get", fake_get)
    result = browser_fetch_module._edeka_http_first(
        "https://www.edeka.de/maerkte/071378/angebote/", 45000
    )
    assert result is not None
    assert requested == [
        "https://www.edeka.de/maerkte/071378/angebote/",
        "https://edeka.de/maerkte/071378/angebote/",
    ]

    requested.clear()

    def malicious_redirect(url, **kwargs):
        requested.append(url)
        request = httpx.Request("GET", url)
        return httpx.Response(302, request=request, headers={"location": "https://example.invalid/offers"})

    monkeypatch.setattr(browser_fetch_module.httpx, "get", malicious_redirect)
    with pytest.raises(BrowserFetchError, match="nicht freigegebenem Host") as caught:
        browser_fetch_module._edeka_http_first(
            "https://www.edeka.de/maerkte/071378/angebote/", 45000
        )
    assert requested == ["https://www.edeka.de/maerkte/071378/angebote/"]
    assert caught.value.diagnostics["block_reason"] == "unapproved_redirect"


def test_fetch_diagnostic_urls_never_persist_arbitrary_query_secrets():
    assert _safe_diagnostic_url(
        "https://www.edeka.de/angebote/?selectedMarktID=071378&token=secret#fragment"
    ) == "https://www.edeka.de/angebote/?selectedMarktID=071378"


def test_browser_navigation_allows_only_official_edeka_https_hosts():
    assert _approved_edeka_navigation("https://www.edeka.de/maerkte/071378/angebote/")
    assert _approved_edeka_navigation("https://edeka.de/angebote/?selectedMarktID=071378")
    assert not _approved_edeka_navigation("http://www.edeka.de/maerkte/071378/angebote/")
    assert not _approved_edeka_navigation("https://www.edeka.de.example.invalid/angebote/")
    assert not _approved_edeka_navigation("https://user:password@www.edeka.de/angebote/")
    assert not _approved_edeka_navigation("https://www.edeka.de:8443/angebote/")
    assert _safe_diagnostic_url(
        "https://www.penny.de/angebote?access_token=secret#fragment"
    ) == "https://www.penny.de/angebote"
    assert _safe_diagnostic_url(
        "https://username:password@www.edeka.de/angebote/?selectedMarktID=071378&token=secret"
    ) == "https://www.edeka.de/angebote/?selectedMarktID=071378"
