from pathlib import Path


def test_collector_market_table_has_mobile_card_layout_and_qa_guidance():
    template = (Path(__file__).parents[1] / "app" / "templates" / "admin_collector.html").read_text(
        encoding="utf-8"
    )
    assert 'class="market-table"' in template
    assert ".market-table td:nth-child(4)::before{content:'Collector / Freshness'}" in template
    assert ".market-table td:nth-child(5)::before{content:'Angebotslage'}" in template
    assert ".market-table td:nth-child(8)::before{content:'Sammlung / QA'}" in template
    assert "QA ist nicht Public" in template
    assert "Die zwölf Beta-Märkte direkt im Collector" in template
    assert "Aktuelle Woche" in template
    assert "Nächste Woche" in template
    assert "Persistierte Quelle" in template
    assert 'href="/admin/rollout"' in template
