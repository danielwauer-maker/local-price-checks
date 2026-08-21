from app.promotion_rules import (
    extract_discount_percent,
    has_multibuy_signal,
    infer_reference_price,
    parse_multibuy,
    promotion_payload,
)


def test_discount_percent_and_plausible_reference_price_are_inferred():
    assert extract_discount_percent("Aktion 0,89 € -41%") == 41.0
    # 0.89 / 0.59 = 1.508...; retail rounding prefers a nearby x,x9 price.
    assert infer_reference_price(0.89, 41.0) == 1.49


def test_explicit_discount_without_reference_can_still_show_normal_price():
    percent = extract_discount_percent("LIDL Aktion -25 % 1,49 €")
    reference = infer_reference_price(1.49, percent)
    assert percent == 25.0
    assert reference is not None
    assert reference > 1.49
    assert int(round(reference * 100)) % 10 == 9


def test_three_for_two_is_resolved_as_bundle_not_single_item_price():
    promo = parse_multibuy("Croissants 3 für 2, je 0,49 €", offer_price=0.49)
    assert promo is not None and promo.valid
    assert promo.kind == "free_item"
    assert promo.buy_quantity == 3
    assert promo.pay_quantity == 2
    assert promo.bundle_price == 0.98
    assert promo.regular_bundle_price == 1.47
    assert promo.savings_amount == 0.49
    assert promo.discount_percent == 33.3
    payload = promotion_payload(promo)
    assert payload["label"] == "3 für 2"


def test_two_plus_one_free_is_resolved_identically():
    promo = parse_multibuy("2 + 1 gratis", offer_price=1.20)
    assert promo is not None and promo.valid
    assert promo.buy_quantity == 3
    assert promo.pay_quantity == 2
    assert promo.bundle_price == 2.40
    assert promo.regular_bundle_price == 3.60


def test_fixed_bundle_is_supported_without_inventing_regular_price():
    promo = parse_multibuy("2 Stück für 3,00 €", offer_price=1.50)
    assert promo is not None and promo.valid
    assert promo.kind == "fixed_bundle"
    assert promo.buy_quantity == 2
    assert promo.bundle_price == 3.00
    assert promo.regular_bundle_price is None


def test_ambiguous_complex_promotion_signal_is_not_claimed_as_valid():
    assert not has_multibuy_signal("gratis Rezeptheft dazu")
    assert parse_multibuy("3 kaufen und irgendeinen Vorteil erhalten", offer_price=1.0) is None
