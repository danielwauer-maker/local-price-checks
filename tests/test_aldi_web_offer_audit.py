from types import SimpleNamespace

from app.aldi_web_offer_audit import (
    ALDI_STATIONARY_OFFERS_URL,
    _to_web_offer,
    fetch_aldi_stationary_chain_audit,
)
from app.engine_v140.browser_fetch import BrowserFetchResult
from app.models import Store


def _store() -> Store:
    return Store(
        id=5,
        retailer="ALDI SÜD",
        name="ALDI SÜD Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Teststraße 1",
        external_id=None,
        active=True,
    )


def _row():
    return SimpleNamespace(
        product_name="Test Kaffee",
        category="Kaffee",
        price=4.99,
        regular_price=None,
        unit_price=9.98,
        quantity=500.0,
        unit="g",
        valid_from="07.09.2026",
        valid_to="12.09.2026",
        source_text="Test Kaffee 500 g 4,99 €",
        image_url="https://www.aldi-sued.de/test.webp",
        image_alt="Test Kaffee",
    )


def test_aldi_chain_offer_conversion_is_explicitly_not_independent_validation():
    offer = _to_web_offer(_store(), _row(), ALDI_STATIONARY_OFFERS_URL)

    assert offer.name == "Test Kaffee"
    assert offer.price == 4.99
    assert offer.packaging_text == "500 g"
    assert str(offer.valid_from) == "2026-09-07"
    assert str(offer.valid_to) == "2026-09-12"
    assert offer.provenance["scope"] == "regional_chain_stationary"
    assert offer.provenance["store_specific"] is False
    assert offer.provenance["independent_external_validation"] is False
    assert offer.provenance["shared_parser_with_production_collector"] is True


def test_aldi_chain_audit_does_not_require_servicepoint_id(monkeypatch):
    import app.aldi_web_offer_audit as module

    monkeypatch.setattr(
        module,
        "parse_aldi_stationary_chain_offers",
        lambda source, text, imgs: [_row()],
    )

    def fetcher(url, **kwargs):
        return BrowserFetchResult(
            content=b"<html><body>ALDI Wochenangebote</body></html>",
            content_type="text/html",
            final_url=ALDI_STATIONARY_OFFERS_URL,
            mode="playwright-1",
        )

    result = fetch_aldi_stationary_chain_audit(_store(), fetcher=fetcher)

    assert result.collector_path == "aldi_stationary_chain_audit"
    assert result.raw_count == 1
    assert len(result.offers) == 1
    assert result.offers[0].name == "Test Kaffee"
    assert result.artifacts["scope"] == "regional_chain_stationary"
    assert result.artifacts["independent_external_validation"] is False


def test_orchestrator_routes_aldi_to_chain_audit(monkeypatch):
    import app.edeka_web_offer_audit_orchestrator as module

    expected = object()
    calls = []

    def fake_run(db, store, period_key="current", source_url=None):
        calls.append((store.retailer, period_key, source_url))
        return expected

    monkeypatch.setattr(module, "run_aldi_web_offer_audit", fake_run)
    store = _store()

    result = module.run_web_offer_audit(
        object(),
        store,
        period_key="current",
        source_url=ALDI_STATIONARY_OFFERS_URL,
    )

    assert result is expected
    assert calls == [("ALDI SÜD", "current", ALDI_STATIONARY_OFFERS_URL)]
