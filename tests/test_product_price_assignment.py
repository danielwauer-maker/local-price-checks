import json
from pathlib import Path

from app.engine_v140.assignment_reconciliation import expected_price_from_unit
from app.promotion_rules import parse_multibuy, promotion_payload


FIXTURE = Path(__file__).parent / "fixtures" / "golden" / "product_price_assignment_2026_kw34.json"


def test_unit_price_economics_reproduce_lidl_page_13_assignments():
    assert expected_price_from_unit(0.33, "l", 6.03, "l") == 1.99
    assert expected_price_from_unit(87, "g", 14.83, "kg") == 1.29
    assert expected_price_from_unit(1.17, "l", 2.98, "l") == 3.49
    assert expected_price_from_unit(720, "g", 5.54, "kg") == 3.99
    assert expected_price_from_unit(310, "g", 12.23, "kg") == 3.79
    assert expected_price_from_unit(240, "g", 12.46, "kg") == 2.99
    assert expected_price_from_unit(200, "g", 16.45, "kg") == 3.29


def test_lidl_plus_is_conditional_and_does_not_replace_normal_offer():
    promo = parse_multibuy(
        "PDF Seite 13 Dr. Oetker 3,99 €\nSPECIAL_PRICE kind=lidl_plus label=Lidl Plus price=3.79",
        offer_price=3.99,
        regular_price=6.78,
    )
    assert promo is not None and promo.valid
    assert promo.kind == "lidl_plus"
    assert promo.bundle_price == 3.79
    assert promo.regular_bundle_price == 3.99
    payload = promotion_payload(promo)
    assert payload["label"] == "Lidl Plus"
    assert payload["bundlePrice"] == 3.79


def test_frozen_manual_assignment_fixture_has_expected_problem_pages():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    edeka = data["edeka"]["pages"]["1"]
    assert len(edeka) == 6
    assert {row["name"] for row in edeka} >= {
        "Himbeeren, rot",
        "Hähnchenschenkel",
        "Delverde Classica Pasta",
        "Doppio Passo",
        "Storck Toffifee",
    }
    lidl13 = data["lidl"]["pages"]["13"]
    expected = {row["name"]: row["price"] for row in lidl13}
    assert expected["Jack Daniel's Mixgetränk"] == 1.99
    assert expected["Milka Tafelschokolade"] == 1.29
    assert expected["Dr. Oetker Ristorante Pizza/Bistro Flammkuchen"] == 3.99
    assert expected["NORDSEE Backfisch"] == 3.79
    assert expected["Grünländer Käsescheiben XXL"] == 2.99
    lidl14 = {row["name"]: row["price"] for row in data["lidl"]["pages"]["14"]}
    assert lidl14["Iglo Fischstäbchen/Filegro XXL"] == 4.99
    assert lidl14["Duplo"] == 3.29
