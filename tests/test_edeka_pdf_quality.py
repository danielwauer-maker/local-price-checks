import json
from pathlib import Path

import pytest

from app.engine_v140.edeka_pdf import (
    _dense_product_name,
    _numeric_price,
    _quantity,
    _unit_price,
)


FIXTURE = Path(__file__).parent / "fixtures" / "edeka_fellenzer_kw34_real_ocr.json"


def test_real_fellenzer_ocr_golden_cards_reach_99_percent_precision_and_recall():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["pdf_sha256"] == "89c7fcd23e0adc36e3227d0f95f26b30943a19955c9b346affcd1d063aa8faa8"
    assert payload["page_count"] == 26
    assert 30 <= len(payload["cards"]) <= 50
    assert len({card["page"] for card in payload["cards"]}) >= 7

    true_positive = false_positive = false_negative = 0
    failures = []
    for card in payload["cards"]:
        expected = card["expected"]
        context = "\n".join(card["ocr_lines"])
        observed = {
            "name": _dense_product_name(card["ocr_lines"]),
            "price": _numeric_price(card["price_token"]),
            "quantity": _quantity(context)[0],
            "unit": _quantity(context)[1],
            "unit_price": _unit_price(context)[0],
            "unit_price_unit": _unit_price(context)[1],
        }
        mismatches = []
        for key, value in expected.items():
            if isinstance(value, (int, float)):
                if observed[key] != pytest.approx(value, abs=0.011):
                    mismatches.append(key)
            elif observed[key] != value:
                mismatches.append(key)
        if mismatches:
            false_negative += 1
            false_positive += 1
            failures.append(f"page={card['page']} name={expected['name']} fields={mismatches} observed={observed}")
        else:
            true_positive += 1

    precision = true_positive / (true_positive + false_positive) * 100
    recall = true_positive / (true_positive + false_negative) * 100
    assert precision >= 99.0, failures
    assert recall >= 99.0, failures


@pytest.mark.parametrize(
    ("raw", "current"),
    [("079", 0.79), ("111", 1.11), ("1099", 10.99), ("29,99", 29.99)],
)
def test_edeka_price_tag_parser_keeps_current_price(raw, current):
    assert _numeric_price(raw) == pytest.approx(current)


def test_edeka_reference_and_unit_price_are_not_current_price():
    context = "Bertolli Olivenöl\nje 500 ml Flasche\n(1 l = € 11.98)\nstatt 7.99"
    assert _quantity(context) == (500.0, "ml")
    assert _unit_price(context) == (11.98, "l")
    assert _numeric_price("599") == pytest.approx(5.99)
