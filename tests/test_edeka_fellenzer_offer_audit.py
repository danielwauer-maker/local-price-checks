from __future__ import annotations

from datetime import date

import pytest

from app.edeka_fellenzer_offer_audit import _parse_html
from app.edeka_web_offer_audit_orchestrator import run_web_offer_audit
from app.models import Store
from app.web_offer_audit import WebAuditError


def _store(external_id: str = "071378") -> Store:
    return Store(
        id=77,
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        postal_code="56305",
        city="Puderbach",
        address="Urbacher Straße 35",
        external_id=external_id,
        active=True,
    )


def test_fellenzer_html_parser_reads_server_rendered_offer_cards():
    html = """
    <html><body>
      <p>Die Angebote der Woche sind gültig vom 31.08. bis zum 05.09.2026.</p>
      <article class="offer-card">
        <img src="https://media.smp-it-media.de/products/image/U3BhcmVfSGltYmVlcmVu" alt="Himbeeren">
        <span class="price">1.79 €</span>
        <h3>Himbeeren</h3>
        <p>Klasse I, 125 g Schale (1 kg = € 14.32)</p>
      </article>
      <article class="offer-card">
        <img src="https://media.smp-it-media.de/product/gurken.jpg" alt="Salatgurken">
        <span class="price">0.88 €</span>
        <h3>Salatgurken</h3>
        <p>Klasse I, Stück</p>
      </article>
    </body></html>
    """

    result = _parse_html(html, _store())

    assert result.collector_path == "edeka_fellenzer_official_html"
    assert result.raw_count == 2
    assert len(result.offers) == 2
    assert result.offers[0].valid_from == date(2026, 8, 31)
    assert result.offers[0].valid_to == date(2026, 9, 5)
    assert {offer.name for offer in result.offers} == {"Himbeeren", "Salatgurken"}
    raspberry = next(offer for offer in result.offers if offer.name == "Himbeeren")
    assert raspberry.price == 1.79
    assert raspberry.quantity_value == 125
    assert raspberry.quantity_unit == "g"
    assert raspberry.image_url == "https://media.smp-it-media.de/products/image/U3BhcmVfSGltYmVlcmVu"
    assert "invalid_image" not in raspberry.validation_errors


def test_orchestrator_falls_back_to_legacy_api_when_combined_source_fails(monkeypatch):
    sentinel = object()

    monkeypatch.setattr(
        "app.edeka_web_offer_audit_orchestrator.fetch_combined_edeka",
        lambda store: (_ for _ in ()).throw(WebAuditError("endpoint_changed", "zentrale Quelle geändert")),
    )
    monkeypatch.setattr(
        "app.edeka_web_offer_audit_orchestrator.run_legacy_edeka_audit",
        lambda db, store, period_key="current", source_url=None: sentinel,
    )

    other_store = _store("123456")
    assert run_web_offer_audit(object(), other_store, period_key="current") is sentinel


def test_fellenzer_combined_failure_does_not_mask_legacy_api_fallback(monkeypatch):
    sentinel = object()

    monkeypatch.setattr(
        "app.edeka_web_offer_audit_orchestrator.fetch_combined_edeka",
        lambda store: (_ for _ in ()).throw(WebAuditError("endpoint_changed", "lokale oder zentrale Quelle geändert")),
    )
    monkeypatch.setattr(
        "app.edeka_web_offer_audit_orchestrator.run_legacy_edeka_audit",
        lambda db, store, period_key="current", source_url=None: sentinel,
    )

    assert run_web_offer_audit(object(), _store(), period_key="current") is sentinel
