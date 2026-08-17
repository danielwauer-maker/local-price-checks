from app.engine_v140 import collectors
from app.engine_v140.browser_fetch import BrowserFetchResult
from app.engine_v140.source_registry import SOURCE_BY_KEY


NETTO_TEXT = """
Netto Marken-Discount
Aktuelle Filial-Angebote
Preissenkung
Online-Wochenangebote
Filial-Angebote
Zu den Angeboten
Filiale
Image
Pfanni Speisekartoffeln 2,5 kg Netz
1.- / kg
Deutschland, unsere Besten, versch. Kocheigenschaften
-24 %
UVP 3.29 2.49*
Filiale
Image
Frau Antje Beste Butter 250 g
3.96 / kg
gekühlt
-66 %
UVP 2.99 0.99*
Filiale
Image
Lenor Waschmittel 15 - 20 WL
0.25 - 0.33 / wl
versch. Sorten
Aktion
4.99*
Aktuelle Prospekte
Filial-Angebote
ab Montag, 17.08.26
"""


def test_netto_parser_handles_current_filial_cards_and_validity():
    source = SOURCE_BY_KEY["netto_dierdorf"]
    offers = collectors.parse_netto_text(source, NETTO_TEXT, [])
    assert len(offers) >= 2
    by_name = {offer.product_name: offer for offer in offers}
    potatoes = next(offer for offer in offers if "Pfanni Speisekartoffeln" in offer.product_name)
    butter = next(offer for offer in offers if "Beste Butter" in offer.product_name)
    assert potatoes.price == 2.49
    assert butter.price == 0.99
    assert potatoes.valid_from == "17.08.2026"
    assert potatoes.valid_to == "22.08.2026"


def test_netto_section_ignores_navigation_heading():
    section = collectors._netto_live_offer_section(NETTO_TEXT)
    assert "Pfanni Speisekartoffeln 2,5 kg Netz" in section
    assert "Preissenkung" not in section


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
