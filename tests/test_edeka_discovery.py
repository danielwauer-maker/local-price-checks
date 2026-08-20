from app.edeka_discovery import _extract_pdf_candidates, _looks_like_pdf_candidate


def test_edeka_smp_extensionless_pdf_endpoint_is_discovered_from_markup():
    base = "https://www.edeka.de/maerkte/999999/angebote/"
    expected = (
        "https://media.smp-it-media.de/flyers/1410-2/pdf?year=2026&week=34&"
        "filename=EDEKA%20Markt%20-%20KW34.pdf"
    )
    markup = f'<script>window.__DATA__={{"prospectUrl":"{expected}"}}</script>'

    assert _extract_pdf_candidates(base, markup) == [expected]
    assert _looks_like_pdf_candidate(expected)


def test_edeka_escaped_json_pdf_url_is_normalized():
    base = "https://www.edeka.de/maerkte/999999/angebote/"
    markup = (
        '<script>{"url":"https:\\/\\/media.smp-it-media.de\\/flyers\\/987-1\\/pdf'
        '?year=2026\\u0026week=34\\u0026filename=Markt.pdf"}</script>'
    )

    candidates = _extract_pdf_candidates(base, markup)

    assert len(candidates) == 1
    assert candidates[0].startswith("https://media.smp-it-media.de/flyers/987-1/pdf?")
    assert "year=2026&week=34&filename=Markt.pdf" in candidates[0]


def test_normal_web_links_are_not_misclassified_as_pdf():
    base = "https://www.edeka.de/maerkte/999999/angebote/"
    markup = '<a href="/angebote/">Angebote</a><a href="/rezepte/">Rezepte</a>'

    assert _extract_pdf_candidates(base, markup) == []
