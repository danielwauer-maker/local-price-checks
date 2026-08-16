from datetime import date

from app.engine_v140.week_utils import infer_validity, parse_any_date


def test_parse_short_date_without_year():
    assert parse_any_date("10.8.", date(2026, 8, 16)) == date(2026, 8, 10)
    assert parse_any_date("16.8", date(2026, 8, 16)) == date(2026, 8, 16)


def test_infer_rewe_short_bis_range():
    text = "Diese Woche Markt geschlossen Nächste Woche 10.8. bis 16.8. Top-Angebote in deinem Markt"
    start, end, source, confidence = infer_validity(text, date(2026, 8, 16))
    assert start == date(2026, 8, 10)
    assert end == date(2026, 8, 16)
    assert source == "short_bis_range"
    assert confidence >= 0.9
