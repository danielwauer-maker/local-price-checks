from app.engine_v140.product_cleaning import product_name_issue


def test_rejects_descriptor_only_product_names():
    bad = [
        "100% pflanzlich",
        "16-18% Vol., versch. Sorten",
        "37,5% Vol. oder Razz 27% Vol.",
        "2er-Set",
        "3er-Set",
        "4er-Set",
    ]
    for name in bad:
        assert product_name_issue(name), name


def test_keeps_real_product_name():
    assert product_name_issue("Axe Bodyspray") is None
