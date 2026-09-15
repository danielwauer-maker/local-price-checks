from datetime import date

from app.engine_v140.week_utils import infer_validity


def test_explicit_this_week_range_preserves_source_published_sunday():
    valid_from, valid_to, source, confidence = infer_validity(
        "Diese Woche 14.9. bis 20.9. Nächste Woche Ab Samstag",
        ref=date(2026, 9, 15),
    )

    assert valid_from == date(2026, 9, 14)
    assert valid_to == date(2026, 9, 20)
    assert source == "this_week_range"
    assert confidence == 0.97


def test_explicit_this_week_range_keeps_saturday_when_source_says_saturday():
    valid_from, valid_to, source, _ = infer_validity(
        "Diese Woche 14.9. bis 19.9.",
        ref=date(2026, 9, 15),
    )

    assert valid_from == date(2026, 9, 14)
    assert valid_to == date(2026, 9, 19)
    assert source == "this_week_range"
