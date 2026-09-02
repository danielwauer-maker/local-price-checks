from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.edeka_fellenzer_offer_audit import _parse_html, fetch_fellenzer_offers
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


def _html() -> str:
    # The production fetch intentionally rejects tiny responses (< 3 KB) as
    # possible CDN/interstitial pages. Keep the fixture realistically sized so
    # fetch tests exercise the parser instead of tripping that safety guard.
    padding = "x" * 3200
    return f"""
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
      <!-- {padding} -->
    </body></html>
    """


def test_fellenzer_html_parser_reads_server_rendered_offer_cards():
    result = _parse_html(_html(), _store())

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


def test_fellenzer_fetch_uses_transparent_profile_and_records_diagnostics():
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, text=_html(), headers={"content-type": "text/html"})

    result = fetch_fellenzer_offers(_store(), http_get=fake_get)

    assert len(result.offers) == 2
    assert calls[0][1]["follow_redirects"] is False
    assert calls[0][1]["headers"]["User-Agent"] == "Spareno-Audit/1.0"
    assert result.artifacts["local_fetch_method"] == "transparent_spareno_audit"
    assert result.artifacts["local_fetch_http_status"] == 200
    assert result.artifacts["local_fetch_final_host"] == "edeka-fellenzer.de"
    assert result.artifacts["local_fetch_block_reason"] is None


def test_fellenzer_fetch_falls_back_to_plain_http_after_transparent_403():
    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs["headers"])
        request = httpx.Request("GET", url)
        if len(calls) == 1:
            return httpx.Response(403, request=request, text="Access Denied", headers={"content-type": "text/html"})
        return httpx.Response(200, request=request, text=_html(), headers={"content-type": "text/html"})

    result = fetch_fellenzer_offers(_store(), http_get=fake_get)

    assert len(calls) == 2
    assert calls[0]["User-Agent"] == "Spareno-Audit/1.0"
    assert "User-Agent" not in calls[1]
    assert result.artifacts["local_fetch_method"] == "plain_http"
    assert result.artifacts["local_fetch_attempts"][0]["block_reason"] == "http_403"


def test_fellenzer_fetch_blocks_redirect_to_foreign_host():
    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(302, request=request, headers={"location": "https://example.invalid/offers"})

    with pytest.raises(WebAuditError, match="Redirect") as caught:
        fetch_fellenzer_offers(_store(), http_get=fake_get)

    assert caught.value.error_type == "blocked"
    assert caught.value.artifacts["local_fetch_block_reason"] == "unapproved_redirect"


def test_orchestrator_persists_failure_when_combined_source_fails(monkeypatch):
    sentinel = object()

    monkeypatch.setattr(
        "app.edeka_web_offer_audit_orchestrator.fetch_combined_edeka",
        lambda store: (_ for _ in ()).throw(WebAuditError("endpoint_changed", "zentrale Quelle geändert")),
    )
    monkeypatch.setattr(
        "app.edeka_web_offer_audit_orchestrator._persist_edeka_failure",
        lambda db, store, period_key, error: sentinel,
    )

    other_store = _store("123456")
    assert run_web_offer_audit(object(), other_store, period_key="current") is sentinel


def test_fellenzer_combined_failure_cannot_be_masked_by_legacy_api(monkeypatch):
    sentinel = object()

    monkeypatch.setattr(
        "app.edeka_web_offer_audit_orchestrator.fetch_combined_edeka",
        lambda store: (_ for _ in ()).throw(WebAuditError("endpoint_changed", "lokale oder zentrale Quelle geändert")),
    )
    monkeypatch.setattr(
        "app.edeka_web_offer_audit_orchestrator._persist_edeka_failure",
        lambda db, store, period_key, error: sentinel,
    )

    assert run_web_offer_audit(object(), _store(), period_key="current") is sentinel
