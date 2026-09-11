from pathlib import Path


def test_web_offer_audit_mobile_offer_cards_and_aldi_validation_warning():
    template = Path("app/templates/admin_web_offer_audit.html").read_text(encoding="utf-8")

    assert "offers-table" in template
    assert "offers-wrap" in template
    assert "QA, nicht extern validiert" in template
    assert "Übereinstimmungswerte prüfen Parser-Konsistenz" in template
    assert ".offers-table td:nth-child(9)::before{content:'Qualität'}" in template
