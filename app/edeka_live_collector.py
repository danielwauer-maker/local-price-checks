from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .clock import app_today
from .collection_quality import BenchmarkContext
from .collection_service import CollectionError, collect_structured_for_store
from .edeka_fellenzer_offer_audit import FELLENZER_MARKET_ID
from .edeka_multi_source_audit import fetch_combined_edeka
from .engine_v140.collectors import CollectedOffer
from .engine_v140.source_registry import source_for_store_record
from .models import Store
from .web_offer_audit import WebOfferRecord


def _market_id(store: Store) -> str:
    return "".join(character for character in str(store.external_id or "") if character.isdigit())


def _source_text(offer: WebOfferRecord) -> str:
    parts = [
        f"Angebot: {offer.name}",
        offer.description,
        offer.packaging_text or offer.quantity,
        offer.discount_text,
    ]
    if offer.provenance:
        parts.append("provenance=" + json.dumps(offer.provenance, ensure_ascii=False, default=str))
    return " | ".join(str(part).strip() for part in parts if part)


def _to_collected_offer(store: Store, offer: WebOfferRecord) -> CollectedOffer:
    return CollectedOffer(
        source_key=f"edeka_web_{_market_id(store) or store.id}",
        store_name=store.name,
        retailer=store.retailer,
        product_name=offer.name,
        category=offer.category or offer.source_category or "Sonstiges",
        price=float(offer.price),
        regular_price=float(offer.old_price) if offer.old_price is not None else None,
        unit_price=float(offer.unit_price) if offer.unit_price is not None else None,
        unit_price_unit=None,
        quantity=float(offer.quantity_value) if offer.quantity_value is not None else None,
        unit=offer.quantity_unit,
        valid_from=offer.valid_from.isoformat() if offer.valid_from else None,
        valid_to=offer.valid_to.isoformat() if offer.valid_to else None,
        source_text=_source_text(offer),
        source_url=offer.source_url,
        image_url=offer.image_url,
        image_alt=offer.image_alt or offer.name,
        local_store_offer=True,
        confidence=0.99,
    )


def _validate_live_scope(store: Store, offers: list[WebOfferRecord], artifacts: dict) -> list[WebOfferRecord]:
    market_id = _market_id(store)
    mismatched = [
        offer for offer in offers
        if offer.store_id != store.id or offer.retailer != "EDEKA"
    ]
    if mismatched:
        raise CollectionError(
            f"EDEKA Live-Collector lieferte {len(mismatched)} Angebote mit falscher Markt-/Händlerbindung."
        )

    if market_id != FELLENZER_MARKET_ID:
        return offers

    source_market_id = str(artifacts.get("market_page_id") or "").strip()
    if source_market_id != FELLENZER_MARKET_ID:
        raise CollectionError(
            f"EDEKA Fellenzer Marktbindung falsch: erwartet={FELLENZER_MARKET_ID} "
            f"quelle={source_market_id or 'unknown'}"
        )

    today = app_today()
    current: list[WebOfferRecord] = []
    invalid_period = 0
    for offer in offers:
        if offer.valid_from is None or offer.valid_to is None:
            invalid_period += 1
            continue
        if offer.valid_from <= today <= offer.valid_to:
            current.append(offer)
        else:
            invalid_period += 1

    if invalid_period:
        raise CollectionError(
            f"EDEKA Fellenzer enthält {invalid_period} nicht aktuell gebundene Angebote; "
            f"Stichtag={today.isoformat()}."
        )
    if not current:
        raise CollectionError(
            f"EDEKA Fellenzer lieferte keine Angebote für {today.isoformat()}."
        )
    return current


def _collect_result(store: Store) -> dict:
    if store.retailer != "EDEKA":
        raise CollectionError(f"Kein EDEKA-Markt: {store.name}")
    if not _market_id(store):
        raise CollectionError(f"EDEKA Markt-ID fehlt: {store.name}")

    audit = fetch_combined_edeka(store)
    artifacts = dict(audit.artifacts or {})
    breakdown = artifacts.get("source_breakdown") or {}
    completeness = (
        artifacts.get("central_completeness_status")
        or artifacts.get("central_completeness")
        or breakdown.get("central_completeness")
    )
    if completeness != "complete":
        raise CollectionError(
            f"EDEKA Zentralquelle nicht vollständig: completeness={completeness or 'unknown'} "
            f"count={len(audit.offers)}"
        )

    # Fellenzer is deliberately configured as central + local supplement. Once
    # it enters the normal collector, a missing local source must be visible as
    # a failed collection instead of silently publishing only the central set.
    local_status = breakdown.get("local_status")
    if _market_id(store) == FELLENZER_MARKET_ID and local_status != "success":
        raise CollectionError(
            f"EDEKA Fellenzer lokale Ergänzungsquelle unvollständig: {local_status or 'unknown'}"
        )

    valid_offers = [offer for offer in audit.offers if offer.valid and offer.price is not None]
    if not valid_offers:
        raise CollectionError(f"EDEKA Web-Collector lieferte keine validen Angebote: {store.name}")
    valid_offers = _validate_live_scope(store, valid_offers, artifacts)

    rows = [_to_collected_offer(store, offer) for offer in valid_offers]
    return {
        "offers": rows,
        "fetch_mode": audit.collector_path,
        "final_url": audit.final_url,
        "source_breakdown": breakdown,
        "audit_raw_count": audit.raw_count,
        "audit_duplicate_count": audit.duplicate_count,
        "market_id": _market_id(store),
        "current_offer_count": len(rows),
        "technical_warning": "" if audit.status == "success" else (audit.message or audit.status),
    }


def collect_edeka_web_for_store(
    db: Session,
    store: Store,
    *,
    benchmark_context: BenchmarkContext | str = BenchmarkContext.NOT_APPLICABLE,
):
    """Import the proven central+local EDEKA web surface into normal Offer rows.

    This is the normal collector/review path, not the audit tables. Publication
    is still controlled exclusively by Market Activation & Quality Gate; merely
    importing rows never sets ``benchmark_verified`` or publishes a store.
    """
    source = source_for_store_record(store)
    if source is None:
        raise CollectionError(f"Keine EDEKA-Quelle für Markt: {store.name}")
    return collect_structured_for_store(
        db,
        store.name,
        source_override=source,
        collector_fn=lambda _source: _collect_result(store),
        benchmark_context=benchmark_context,
    )
