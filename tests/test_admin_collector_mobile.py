from pathlib import Path


def test_collector_market_table_has_mobile_card_layout_and_qa_guidance():
    template = (Path(__file__).parents[1] / "app" / "templates" / "admin_collector.html").read_text(
        encoding="utf-8"
    )
    assert 'class="market-table"' in template
    assert ".market-table td:nth-child(8)::before{content:'Sammlung / QA'}" in template
    assert "QA ist nicht Public" in template
    assert 'href="/admin/rollout"' in template
