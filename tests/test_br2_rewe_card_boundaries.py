from app.engine_v140.collectors import parse_rewe_text
from app.engine_v140.source_registry import RetailSource


def _source():
    return RetailSource(
        key="rewe-test",
        retailer="REWE",
        store_name="REWE Dierdorf",
        url="https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
        mode="store_page",
        locality="store_specific",
        store_specific=True,
    )


def test_rewe_does_not_borrow_previous_card_package():
    text = """
Previous Product
500 ml
Aktion
5,49 €
Actual Product Without Package
Knaller
0,79 €
"""

    offers = parse_rewe_text(_source(), text)

    assert len(offers) == 1
    assert offers[0].product_name == "Previous Product"
    assert offers[0].price == 5.49
    assert offers[0].quantity == 500.0
    assert offers[0].unit == "ml"


def test_rewe_skips_lowercase_descriptive_copy_when_selecting_title():
    text = """
REWE Bio Pflanzlich Hummus
extra
je 200-g-Pckg.
(1 kg = 3,95 €)
Aktion
0,79 €
"""

    offers = parse_rewe_text(_source(), text)

    assert len(offers) == 1
    assert offers[0].product_name == "REWE Bio Pflanzlich Hummus"
    assert offers[0].price == 0.79
    assert offers[0].quantity == 200.0
    assert offers[0].unit == "g"


def test_rewe_generic_copy_cannot_win_via_image_alt_match():
    text = """
Jacobs Auslese oder Meisterröstung
extra
500 g
Aktion
5,49 €
"""
    images = [
        {"url": "https://example.invalid/extra.webp", "alt": "extra"},
        {"url": "https://example.invalid/jacobs.webp", "alt": "Jacobs Auslese oder Meisterröstung"},
    ]

    offers = parse_rewe_text(_source(), text, images)

    assert len(offers) == 1
    assert offers[0].product_name == "Jacobs Auslese oder Meisterröstung"
    assert offers[0].price == 5.49
    assert offers[0].quantity == 500.0
    assert offers[0].unit == "g"


def test_rewe_keeps_single_word_capitalized_product_titles():
    text = """
Bananen
je 1-kg-Bund
Aktion
0,79 €
"""

    offers = parse_rewe_text(_source(), text)

    assert len(offers) == 1
    assert offers[0].product_name == "Bananen"
    assert offers[0].quantity == 1.0
    assert offers[0].unit == "kg"
