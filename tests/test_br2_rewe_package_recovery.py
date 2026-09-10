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


def test_rewe_package_line_wins_over_nearer_unit_price_line():
    text = """
Milram Müritzer Scheiben
Original, je 150-g-Pckg.
(1 kg = 8,60 €)
Knaller
1,29 €
"""

    offers = parse_rewe_text(_source(), text)

    assert len(offers) == 1
    assert offers[0].product_name == "Milram Müritzer Scheiben"
    assert offers[0].price == 1.29
    assert offers[0].quantity == 150.0
    assert offers[0].unit == "g"


def test_rewe_multi_pack_is_normalized_to_total_quantity():
    text = """
Kinder Country
je 9 x 23,5-g-Pckg.
(1 kg = 11,77 €)
Aktion
2,49 €
"""

    offers = parse_rewe_text(_source(), text)

    assert len(offers) == 1
    assert offers[0].product_name == "Kinder Country"
    assert offers[0].quantity == 211.5
    assert offers[0].unit == "g"
