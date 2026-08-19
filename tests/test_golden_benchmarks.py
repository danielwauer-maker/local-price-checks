from pathlib import Path

import pytest

from app.golden_benchmarks import run_golden_benchmark


FIXTURES = Path(__file__).parent / "fixtures" / "golden"
RETAILERS = [
    "rewe",
    "lidl",
    "netto",
    "aldi_sued",
    "edeka",
    "penny",
    "aldi_nord",
]


@pytest.mark.parametrize("retailer", RETAILERS)
def test_retailer_golden_benchmark_meets_precision_and_recall_target(retailer):
    result = run_golden_benchmark(FIXTURES / f"{retailer}.json")

    assert result.precision >= 99.0, result.failures
    assert result.recall >= 99.0, result.failures
    assert result.status == "PASS"


def test_rewe_golden_fixture_retains_negative_name_samples():
    result = run_golden_benchmark(FIXTURES / "rewe.json")
    assert result.status == "PASS"
    assert not result.failures


def test_lidl_golden_fixture_excludes_online_only_offer():
    result = run_golden_benchmark(FIXTURES / "lidl.json")
    assert result.status == "PASS"
    assert result.precision == 100.0
