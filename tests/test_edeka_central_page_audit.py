from __future__ import annotations

from app.edeka_central_page_audit import _category_diagnostics, fetch_central_market_page
from app.engine_v140.browser_fetch import BrowserFetchResult
from app.models import Store


def _store(external_id: str = "071378") -> Store:
    return Store(
        id=77, retailer="EDEKA", name="EDEKA Fellenzer", postal_code="56305",
        city="Puderbach", address="Urbacher Straße 35", external_id=external_id, active=True,
    )


def _article(index: int, hidden: bool = False) -> str:
    state = "false" if hidden else "true"
    return f'''<li id="filter-results-item-{index}" data-show-by-filter="true" data-show-by-load-more="{state}">
      <article><h4><a href="#angebot-{index}"><span>Angebot:</span> Artikel {index}</a></h4>
      <span>Festpreis von {1 + index / 100:.2f}€</span><p>500 g Packung</p></article></li>'''


def _surface(category_counts: list[int], featured: int = 0) -> str:
    chunks = ["<html><body>"]
    index = 0
    for category_index, count in enumerate(category_counts):
        rows = []
        for row_index in range(count):
            rows.append(_article(index, hidden=row_index >= 8))
            index += 1
        chunks.append(
            f'<load-more data-max-items="8"><ul id="filter-results-group-list-category-{category_index}">'
            + "".join(rows)
            + '<button id="load-more-button">Mehr laden</button></ul></load-more>'
        )
    for _ in range(featured):
        chunks.append(
            f'<article><h4><a href="#angebot-{index}">Highlight {index}</a></h4>'
            f'<span>Festpreis von {1 + index / 100:.2f}€</span></article>'
        )
        index += 1
    chunks.append("</body></html>")
    return "".join(chunks)


def _fetcher(html: str, diagnostics: dict | None = None, mode: str = "fixture"):
    def fetch(url, **kwargs):
        return BrowserFetchResult(
            html.encode(), "text/html", url, mode, diagnostics=diagnostics or {}
        )
    return fetch


def test_real_load_more_shape_counts_hidden_server_rendered_rows():
    html = _surface([23, 34, 47, 11, 40, 32, 19, 14], featured=4)
    diagnostics = _category_diagnostics(html, "071378")

    assert diagnostics["server_rendered_category_count"] == 220
    assert diagnostics["server_rendered_offer_count"] == 224
    assert diagnostics["featured_offer_count"] == 4
    assert diagnostics["categories_detected"] == 8
    assert diagnostics["central_category_counts"]["category-2"] == 47
    assert [row["initial_visible_count"] for row in diagnostics["categories"]] == [8] * 8
    assert diagnostics["categories"][0]["required_visibility_batches"] == 2
    assert diagnostics["categories"][2]["required_visibility_batches"] == 5
    assert diagnostics["load_more_mechanism"] == "server_rendered_dom_data_attribute_toggle"


def test_known_fellenzer_reference_is_complete_at_historical_224():
    full = _surface([23, 34, 47, 11, 40, 32, 19, 14], featured=4)
    result = fetch_central_market_page(_store(), fetcher=_fetcher(full, {
        "http_status": 200,
        "http_version": "HTTP/1.1",
        "final_host": "www.edeka.de",
        "response_headers": {"content-type": "text/html"},
        "redirect_chain": [],
        "fallback_used": False,
    }, mode="http-edeka-server-rendered"))

    assert result.status == "success"
    assert result.collector_path == "edeka_central_market_page_dom"
    assert len(result.offers) == 224
    assert result.artifacts["central_completeness"] == "complete"
    assert result.artifacts["known_reference_count"] == 224
    assert result.artifacts["reference_minimum_count"] == 213
    assert result.artifacts["reference_coverage_ratio"] == 1.0
    assert result.artifacts["central_categories_completed"] == 8
    assert result.artifacts["unparsed_dom_offer_count"] == 0
    assert result.source_url == "https://www.edeka.de/maerkte/071378/angebote/"
    assert {row.source_category for row in result.offers if row.source_category} >= {"highlight", "category-0"}
    assert result.artifacts["central_fetch_method"] == "DOM_DIRECT"
    assert result.artifacts["central_fetch_http_status"] == 200
    assert result.artifacts["central_fetch_final_host"] == "www.edeka.de"
    assert result.artifacts["central_dom_count"] == 224
    assert result.artifacts["central_parsed_count"] == 224
    assert result.artifacts["central_reference_count"] == 224


def test_fellenzer_complete_dom_accepts_normal_weekly_count_drift():
    current_week = _surface([23, 34, 47, 11, 40, 32, 19, 13], featured=4)
    result = fetch_central_market_page(_store(), fetcher=_fetcher(current_week))

    assert len(result.offers) == 223
    assert result.status == "success"
    assert result.artifacts["central_completeness"] == "complete"
    assert result.artifacts["reference_minimum_count"] == 213
    assert result.artifacts["reference_coverage_ratio"] > 0.99
    assert result.artifacts["unparsed_dom_offer_count"] == 0


def test_fellenzer_reference_collapse_below_95_percent_stays_partial():
    collapsed = _surface([22, 32, 44, 10, 38, 30, 18, 14], featured=4)
    result = fetch_central_market_page(_store(), fetcher=_fetcher(collapsed))

    assert len(result.offers) == 212
    assert result.status == "partial"
    assert result.artifacts["central_completeness"] == "partial"
    assert result.artifacts["reference_minimum_count"] == 213


def test_small_dom_result_is_partial_and_never_reported_as_success():
    partial = _surface([10, 10])
    result = fetch_central_market_page(_store(), fetcher=_fetcher(partial))

    assert len(result.offers) == 20
    assert result.status == "partial"
    assert result.artifacts["central_completeness"] == "partial"
    assert result.artifacts["parsed_central_count"] == 20
    assert result.artifacts["central_completeness_status"] == "partial"


def test_known_224_reference_is_scoped_to_fellenzer_only():
    diagnostics = _category_diagnostics(_surface([10]), "099999")
    assert diagnostics["known_reference_count"] is None
