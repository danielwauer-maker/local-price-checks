from types import SimpleNamespace

from app.engine_v140.offer_quality import evaluate_offer


def _offer(name: str):
    return SimpleNamespace(
        product_name=name,
        price=9.99,
        quantity=0.7,
        unit="l",
        unit_price=14.27,
        confidence=0.9,
    )


def test_numeric_product_qualifier_makes_short_name_specific_enough():
    quality = evaluate_offer(_offer("Ouzo 12"))

    assert quality.accepted is True
    assert "Einzelwort zu unspezifisch" not in quality.reasons


def test_short_single_word_without_numeric_qualifier_remains_rejected():
    quality = evaluate_offer(_offer("Ouzo"))

    assert quality.accepted is False
    assert quality.reasons == ("Einzelwort zu unspezifisch",)


def test_numeric_only_name_remains_rejected():
    quality = evaluate_offer(_offer("12"))

    assert quality.accepted is False
    assert quality.reasons == ("Keine Produktbezeichnung erkennbar",)
