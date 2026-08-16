from datetime import date

from app.engine_v140 import prospect_pdf_engine as e
from app.engine_v140.source_registry import RetailSource


def test_v140_engine_imports_and_filters_price_noise():
    assert e._extract_current_price("Knaller\n3.79", "REWE") == 3.79
    assert e._extract_current_price("zzgl. 0.25 Pfand\nAktion\n0.79", "REWE") == 0.79


def test_v140_quantity_and_base_price_parsing():
    q, unit = e._extract_quantity("je 500-g-Pckg. (1 kg = 12.98)")
    assert q == 500
    assert unit == "g"
    up, up_unit = e._extract_unit_price("je 500-g-Pckg. (1 kg = 12.98)")
    assert up == 12.98
    assert up_unit == "kg"


def test_v140_rewe_market_id_guard_helper():
    assert e._market_id("", "rewe_2026_wk33_321019.pdf") == "321019"


def test_v140_source_contract():
    source = RetailSource(
        "bench", "REWE", "REWE Test", "https://www.rewe.de/angebote/x/321019/x/",
        "store_page", "store_specific"
    )
    assert source.retailer == "REWE"
