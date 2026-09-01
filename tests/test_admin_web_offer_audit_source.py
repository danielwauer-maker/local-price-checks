from app.admin_web_offer_audit_routes import _audit_source_url
from app.models import Store


def _store(retailer: str, external_id: str | None, source_url: str | None) -> Store:
    return Store(
        id=1,
        retailer=retailer,
        name="Testmarkt",
        postal_code="56305",
        city="Puderbach",
        address="Testweg 1",
        external_id=external_id,
        source_url=source_url,
        active=True,
    )


def test_edeka_audit_uses_central_offer_url_from_external_market_id():
    store = _store("EDEKA", "071378", "https://www.edeka.de/marktseite/test")
    assert _audit_source_url(store) == "https://www.edeka.de/maerkte/071378/angebote/"


def test_edeka_audit_preserves_leading_zero_when_id_contains_prefix():
    store = _store("EDEKA", "edeka-071378", None)
    assert _audit_source_url(store) == "https://www.edeka.de/maerkte/071378/angebote/"


def test_other_retailers_keep_persisted_reviewed_source_url():
    store = _store("PENNY", "4030882", "https://www.penny.de/angebote")
    assert _audit_source_url(store) == "https://www.penny.de/angebote"


def test_edeka_without_external_id_falls_back_to_persisted_source_url():
    store = _store("EDEKA", None, "https://www.edeka.de/maerkte/example/angebote/")
    assert _audit_source_url(store) == "https://www.edeka.de/maerkte/example/angebote/"
