from app.engine_v140 import collectors
from app.engine_v140.browser_fetch import BrowserFetchResult
from app.engine_v140.source_registry import SOURCE_BY_KEY


NETTO_TEXT = """
Netto Marken-Discount
Filial-Angebote
gültig von Montag, 17.08.26 - Samstag, 22.08.26
Filiale
Jacobs Krönung Kaffee 500 g
12.98 / kg
gemahlen oder ganze Bohnen, versch. Sorten
statt 9.99 6.49
"""


def test_netto_parser_attaches_page_validity():
    source = SOURCE_BY_KEY["netto_dierdorf"]
    offers = collectors.parse_netto_text(source, NETTO_TEXT, [])
    assert offers
    assert offers[0].valid_from == "17.08.2026"
    assert offers[0].valid_to == "22.08.2026"


def test_netto_retries_rendered_page_when_http_shell_has_no_offers(monkeypatch):
    source = SOURCE_BY_KEY["netto_dierdorf"]

    monkeypatch.setattr(
        collectors,
        "_base_collect_one",
        lambda _source: {
            "source": _source,
            "raw": b"<html></html>",
            "content_type": "text/html",
            "fetch_mode": "http",
            "final_url": _source.url,
            "offers": [],
            "status": "no_safe_offers",
        },
    )
    monkeypatch.setattr(
        collectors,
        "browser_fetch",
        lambda _url: BrowserFetchResult(
            content=("<html><body>" + NETTO_TEXT.replace("\n", "<br>") + "</body></html>").encode(),
            content_type="text/html; charset=utf-8",
            final_url=source.url,
            mode="playwright-test",
        ),
    )

    result = collectors.collect_one(source)
    assert result["fetch_mode"] == "playwright-test"
    assert result["offers"]
    assert result["offers"][0].valid_from == "17.08.2026"
