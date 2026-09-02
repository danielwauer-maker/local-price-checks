from pathlib import Path


def test_edeka_audit_separates_cross_source_same_source_and_internal_duplicate_labels():
    template = Path("app/templates/admin_web_offer_audit.html").read_text(encoding="utf-8")

    assert "Cross-Source Dedupe-Kandidaten" in template
    assert "Same-Source Varianten" in template
    assert "Interne echte Duplikate" in template
    assert "<th>Variante A</th><th>Variante B</th>" in template
    assert "source_same_source_variant_count" in template
    assert "source_internal_duplicate_count" in template


def test_same_source_rows_use_variant_specific_price_and_image_labels():
    template = Path("app/templates/admin_web_offer_audit.html").read_text(encoding="utf-8")

    assert "same_source_name_diagnostic" in template
    assert "Bild A" in template
    assert "Bild B" in template
    assert "A {{ d.get('central_price')" in template
    assert "B {{ d.get('local_price')" in template
