from datetime import date
import json

from app.engine_v140 import collectors
from app.engine_v140.rewe_week_horizon import (
    append_rewe_audit_appendix,
    parse_rewe_structured_weeks,
    visible_next_week_is_published,
)
from app.engine_v140.source_registry import RetailSource


def _source():
    return RetailSource(
        key="rewe-dierdorf",
        retailer="REWE",
        store_name="REWE:XL Hundertmark",
        url="https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
        mode="store_page",
        locality="store_specific",
        store_specific=True,
    )


def _offer(title, price, subtitle="je 500-g-Pckg., (1 kg = 3,98 €)"):
    return {
        "cellType": "DEFAULT",
        "overline": "Aktion",
        "title": title,
        "subtitle": subtitle,
        "images": [{"url": f"https://img.rewe-static.de/{title.lower().replace(' ', '-')}.webp"}],
        "priceData": {
            "price": price,
            "regularPrice": "UVP 9,99 €",
        },
    }


def _week(start, end, offers, *, available=True):
    return {
        "available": available,
        "fromDate": start,
        "untilDate": end,
        "categories": [
            {
                "id": "cat-1",
                "title": "Testkategorie",
                "order": 1,
                "offers": offers,
            }
        ],
    }


def _document(*, next_available=True, next_start="2026-09-21", next_end="2026-09-27"):
    payload = [
        {
            "url": "https://www.rewe.de/internal/stationary-offers/321019",
            "data": {
                "data": {
                    "offers": {
                        "defaultWeek": "current",
                        "nextWeekAvailableFrom": "saturday",
                        "current": _week(
                            "2026-09-14",
                            "2026-09-20",
                            [_offer("Milka Schokolade", "0,99 €", "je 90-g-Tafel, (1 kg = 11,00 €)")],
                        ),
                        "next": _week(
                            next_start,
                            next_end,
                            [_offer("Milka Schokolade", "0,89 €", "je 90-g-Tafel, (1 kg = 9,89 €)")],
                            available=next_available,
                        ),
                    }
                }
            },
        }
    ]
    return (
        "<html><body><h1>REWE Angebote</h1>"
        '<script id="lpc-network-json" type="application/json">'
        + json.dumps(payload, ensure_ascii=False)
        + "</script></body></html>"
    )


def test_structured_rewe_keeps_current_and_next_as_separate_cohorts():
    rows, meta = parse_rewe_structured_weeks(_document(), ref=date(2026, 9, 15))

    assert meta["structured_found"] is True
    assert meta["next_available"] is True
    assert meta["current_count"] == 1
    assert meta["next_count"] == 1
    assert meta["errors"] == []
    assert [(row["period"], row["valid_from"], row["valid_to"]) for row in rows] == [
        ("current", "14.09.2026", "20.09.2026"),
        ("next", "21.09.2026", "27.09.2026"),
    ]
    # Same product may legitimately occur again next week and must not collapse.
    assert [row["product_name"] for row in rows] == ["Milka Schokolade", "Milka Schokolade"]
    assert [row["price"] for row in rows] == [0.99, 0.89]


def test_structured_rewe_never_promotes_advertised_reference_price_to_regular_price():
    rows, _ = parse_rewe_structured_weeks(_document(), ref=date(2026, 9, 15))

    assert rows
    assert all(row["regular_price"] is None for row in rows)
    assert "UVP 9,99" not in " ".join(row["source_text"] for row in rows)


def test_rewe_next_week_unavailable_means_current_only():
    rows, meta = parse_rewe_structured_weeks(
        _document(next_available=False),
        ref=date(2026, 9, 15),
    )

    assert meta["next_available"] is False
    assert meta["current_count"] == 1
    assert meta["next_count"] == 0
    assert {row["period"] for row in rows} == {"current"}


def test_rewe_rejects_structured_next_week_beyond_allowed_horizon():
    rows, meta = parse_rewe_structured_weeks(
        _document(next_start="2026-09-28", next_end="2026-10-04"),
        ref=date(2026, 9, 15),
    )

    assert {row["period"] for row in rows} == {"current"}
    assert meta["next_count"] == 0
    assert "next_out_of_horizon" in meta["errors"]


def test_rewe_ab_samstag_is_not_treated_as_published_next_week():
    text = "Diese Woche 14.9. bis 20.9. Nächste Woche Ab Samstag"
    assert visible_next_week_is_published(text, ref=date(2026, 9, 15)) is False


def test_rewe_explicit_dated_next_week_is_treated_as_published():
    text = "Diese Woche 14.9. bis 20.9. Nächste Woche 21.9. bis 27.9."
    assert visible_next_week_is_published(text, ref=date(2026, 9, 15)) is True


def test_rewe_audit_appendix_contains_both_week_labels_and_offer_names():
    rows, _ = parse_rewe_structured_weeks(_document(), ref=date(2026, 9, 15))
    rendered = append_rewe_audit_appendix("<html><body>Original</body></html>", rows)

    assert "Spareno Prüfanhang" in rendered
    assert "Aktuelle Woche" in rendered
    assert "Nächste Woche" in rendered
    assert rendered.count("Milka Schokolade") == 2
    assert rendered.index("Original") < rendered.index("Spareno Prüfanhang")


def test_collect_one_supplements_missing_next_cohort_from_same_captured_rewe_response(monkeypatch):
    current_page = """
    <html><body>
      <div>Diese Woche 14.9. bis 20.9.</div>
      <div>Nächste Woche Ab Samstag</div>
      <div>Milka Schokolade</div>
      <div>je 90-g-Tafel, (1 kg = 11,00 €)</div>
      <div>Aktion</div>
      <div>0,99 €</div>
    """
    structured_script = _document().split("<body>", 1)[1].split("</body>", 1)[0]
    page = current_page + structured_script + "</body></html>"

    monkeypatch.setattr(
        collectors,
        "fetch_source",
        lambda source: (page.encode("utf-8"), "text/html; charset=utf-8", "fixture-http", source.url),
    )

    result = collectors.collect_one(_source())

    periods = {(row.valid_from, row.valid_to, row.price) for row in result["offers"]}
    assert ("14.09.2026", "20.09.2026", 0.99) in periods
    assert ("21.09.2026", "27.09.2026", 0.89) in periods
    assert result["rewe_current_offer_count"] >= 1
    assert result["rewe_next_week_offer_count"] == 1
    assert result["rewe_structured_found"] is True
    assert result["rewe_structured_next_available"] is True
    assert "technical_warning" not in result
    assert b"Spareno Pr\xc3\xbcfanhang" in result["raw"]


def test_collect_one_does_not_open_browser_while_rewe_only_says_ab_samstag(monkeypatch):
    page = """
    <html><body>
      <div>Diese Woche 14.9. bis 20.9.</div>
      <div>Nächste Woche Ab Samstag</div>
      <div>Milka Schokolade</div>
      <div>je 90-g-Tafel, (1 kg = 11,00 €)</div>
      <div>Aktion</div>
      <div>0,99 €</div>
    </body></html>
    """
    monkeypatch.setattr(
        collectors,
        "fetch_source",
        lambda source: (page.encode("utf-8"), "text/html; charset=utf-8", "fixture-http", source.url),
    )

    def browser_must_not_run(*_args, **_kwargs):
        raise AssertionError("Browser darf vor Veröffentlichung der nächsten Woche nicht gestartet werden")

    monkeypatch.setattr(collectors, "browser_fetch", browser_must_not_run)

    result = collectors.collect_one(_source())

    assert result["fetch_mode"] == "fixture-http"
    assert result["rewe_next_week_offer_count"] == 0
    assert "technical_warning" not in result
