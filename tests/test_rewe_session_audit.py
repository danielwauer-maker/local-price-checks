from types import SimpleNamespace

from app.rewe_audit_runtime import _validity_from_result


def test_rewe_session_audit_uses_offer_validity():
    result = {
        "offers": [
            SimpleNamespace(valid_from="17.08.2026", valid_to="22.08.2026"),
            SimpleNamespace(valid_from="17.08.2026", valid_to="22.08.2026"),
        ]
    }
    valid_from, valid_to = _validity_from_result(result)
    assert valid_from.isoformat() == "2026-08-17"
    assert valid_to.isoformat() == "2026-08-22"


def test_rewe_session_audit_accepts_iso_dates():
    result = {"offers": [SimpleNamespace(valid_from="2026-08-17", valid_to="2026-08-22")]}
    valid_from, valid_to = _validity_from_result(result)
    assert valid_from.isoformat() == "2026-08-17"
    assert valid_to.isoformat() == "2026-08-22"
