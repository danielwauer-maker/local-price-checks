from app.admin_prospect_audit_routes import _optional_positive_int


def test_optional_positive_int_accepts_empty_query_values():
    assert _optional_positive_int(None) is None
    assert _optional_positive_int("") is None
    assert _optional_positive_int("   ") is None


def test_optional_positive_int_parses_valid_values():
    assert _optional_positive_int("12") == 12
    assert _optional_positive_int(7) == 7


def test_optional_positive_int_rejects_invalid_values_without_raising():
    assert _optional_positive_int("abc") is None
    assert _optional_positive_int("0") is None
    assert _optional_positive_int("-2") is None
