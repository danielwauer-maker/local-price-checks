from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import time
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import Store
from .web_offer_audit import (
    WebAuditError,
    WebAuditResult,
    WebOfferRecord,
    _clean,
    _number,
    _quantity,
    valid_product_image,
)
from .web_offer_audit_models import WebOfferAuditItem, WebOfferAuditRun
from .web_offer_audit_runtime import (
    _comparison,
    _write_artifact,
    filter_period_overlap,
    quality_deduplicate,
    run_web_offer_audit as run_legacy_web_offer_audit,
)

EDEKA_OFFERS_ENDPOINT = "https://www.edeka.de/eh/service/eh/offers"


def _epoch_date(value: object):
    if value in (None, ""):
        return None
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return datetime.fromtimestamp(number, tz=timezone.utc).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _first(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _parse_edeka_doc(row: dict, store: Store, source_url: str) -> WebOfferRecord | None:
    name = _clean(_first(row, "titel", "title", "name"))
    price = _number(_first(row, "preis", "price", "offerPrice"))
    if not name or price is None:
        return None

    description = _clean(_first(row, "beschreibung", "description")) or None
    basic_price = _first(row, "basicPrice", "grundpreis", "unitPrice")
    quantity_source = " ".join(part for part in (name, description or "") if part)
    quantity, quantity_value, quantity_unit = _quantity(quantity_source)
    image_url = _clean(_first(row, "bild_app", "bild", "image", "imageUrl")) or None
    if image_url and not valid_product_image(image_url):
        image_url = None

    return WebOfferRecord(
        retailer="EDEKA",
        store_id=store.id,
        source_url=source_url,
        external_offer_id=_clean(_first(row, "angebotid", "angebotId", "offerId", "id")) or None,
        external_product_id=_clean(_first(row, "artikelid", "artikelId", "productId", "sku")) or None,
        ean=_clean(_first(row, "ean", "gtin")) or None,
        name=name,
        brand=_clean(_first(row, "marke", "brand", "hersteller")) or None,
        description=description,
        price=price,
        old_price=_number(_first(row, "normalpreis", "originalpreis", "oldPrice", "regularPrice")),
        unit_price=_number(basic_price),
        quantity=quantity,
        quantity_value=quantity_value,
        quantity_unit=quantity_unit,
        packaging_text=quantity,
        valid_from=_epoch_date(_first(row, "gueltig_von", "gueltigVon", "validFrom", "startDate")),
        valid_to=_epoch_date(_first(row, "gueltig_bis", "gueltigBis", "validTo", "endDate")),
        category=_clean(_first(row, "warengruppe", "category", "categoryName")) or None,
        source_category=_clean(_first(row, "warengruppe", "category", "categoryName")) or None,
        image_url=image_url,
        image_source="edeka_web_api" if image_url else None,
        image_alt=name if image_url else None,
        provenance={
            "api_endpoint": EDEKA_OFFERS_ENDPOINT,
            "market_id": str(store.external_id or ""),
            "keys": sorted(str(key) for key in row.keys())[:100],
            "basic_price_raw": _clean(basic_price) or None,
        },
    )


def _fetch_edeka_api(store: Store, http_get=httpx.get) -> WebAuditResult:
    if not store.external_id:
        raise WebAuditError("browser_required", "EDEKA benötigt eine verifizierte Markt-ID für den Angebots-API-Audit.")
    market_id = "".join(character for character in str(store.external_id).strip() if character.isdigit())
    if not market_id:
        raise WebAuditError("browser_required", "EDEKA-Markt-ID enthält keine nutzbare numerische ID.")

    params = {"marketId": market_id, "limit": 99999}
    request_url = f"{EDEKA_OFFERS_ENDPOINT}?{urlencode(params)}"
    started = time.monotonic()
    try:
        response = http_get(
            EDEKA_OFFERS_ENDPOINT,
            params=params,
            follow_redirects=True,
            timeout=settings.collector_timeout_seconds,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
                "User-Agent": "Spareno-Web-Audit/1.0",
            },
        )
    except httpx.TimeoutException as exc:
        raise WebAuditError(
            "timeout",
            f"EDEKA Angebots-API Timeout: {exc}",
            {"fetch_mode": "edeka-web-api-http", "api_url": request_url},
        ) from exc
    except httpx.HTTPError as exc:
        raise WebAuditError(
            "endpoint_changed",
            f"EDEKA Angebots-API HTTP-Fehler: {exc}",
            {"fetch_mode": "edeka-web-api-http", "api_url": request_url},
        ) from exc

    content_type = response.headers.get("content-type", "")
    diagnostics = {
        "fetch_mode": "edeka-web-api-http",
        "api_url": request_url,
        "http_status": response.status_code,
        "content_type": content_type,
        "response_bytes": len(response.content),
        "final_url": str(response.url),
        "network_payloads": [],
        "console_errors": [],
        "failed_requests": [],
    }
    if response.status_code in {401, 403, 429}:
        raise WebAuditError(
            "blocked",
            f"EDEKA Angebots-API antwortet mit HTTP {response.status_code}; kein Browser-Fallback und keine Umgehung wird versucht.",
            diagnostics,
        )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise WebAuditError(
            "endpoint_changed",
            f"EDEKA Angebots-API antwortet mit HTTP {response.status_code}.",
            diagnostics,
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise WebAuditError(
            "invalid_json",
            f"EDEKA Angebots-API lieferte kein gültiges JSON (HTTP {response.status_code}, {content_type or 'ohne Content-Type'}).",
            diagnostics,
        ) from exc
    if not isinstance(payload, dict):
        raise WebAuditError("invalid_json", "EDEKA Angebots-API lieferte kein JSON-Objekt.", diagnostics)
    docs = payload.get("docs")
    if not isinstance(docs, list):
        diagnostics["response_keys"] = sorted(str(key) for key in payload.keys())[:100]
        raise WebAuditError("endpoint_changed", "EDEKA Angebots-API enthält kein erwartetes 'docs'-Array.", diagnostics)

    raw = [_parse_edeka_doc(row, store, request_url) for row in docs if isinstance(row, dict)]
    raw = [row for row in raw if row is not None]
    offers, duplicates = quality_deduplicate(raw)
    if not offers:
        diagnostics["docs_count"] = len(docs)
        diagnostics["parsed_count"] = len(raw)
        raise WebAuditError("empty", "EDEKA Angebots-API lieferte keine validen Angebotsdatensätze.", diagnostics)

    diagnostics["docs_count"] = len(docs)
    diagnostics["parsed_count"] = len(raw)
    diagnostics["response_keys"] = sorted(str(key) for key in payload.keys())[:100]
    return WebAuditResult(
        offers=offers,
        source_url=request_url,
        final_url=str(response.url),
        collector_path="edeka_web_offer_api",
        raw_count=len(raw),
        duplicate_count=duplicates,
        message=f"{round((time.monotonic() - started) * 1000)} ms via EDEKA Web API",
        artifacts=diagnostics,
    )


def _persist_edeka_result(db: Session, store: Store, period_key: str, result: WebAuditResult) -> WebOfferAuditRun:
    filtered = filter_period_overlap(result.offers, period_key, "EDEKA")
    filtered, extra_duplicates = quality_deduplicate(filtered)
    result.offers = filtered
    result.duplicate_count += extra_duplicates

    run = WebOfferAuditRun(
        store_id=store.id,
        retailer=store.retailer,
        period_key=period_key,
        source_url=result.source_url,
        final_url=result.final_url,
        collector_path=result.collector_path,
        status="success",
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        duration_ms=0,
        raw_count=result.raw_count,
        duplicate_count=result.duplicate_count,
        valid_count=sum(row.valid for row in filtered),
        missing_price_count=sum(row.price is None for row in filtered),
        missing_image_count=sum(not row.image_url for row in filtered),
        missing_package_count=sum(not row.packaging_text for row in filtered),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    comparison = _comparison(db, store, filtered, period_key)
    run.comparison_json = json.dumps(comparison, ensure_ascii=False)
    for row in filtered:
        data = asdict(row)
        provenance = data.pop("provenance")
        errors = data.pop("validation_errors")
        data["provenance_json"] = json.dumps(provenance, ensure_ascii=False, default=str)
        data["validation_errors"] = ",".join(errors) or None
        data["dedupe_key"] = row.dedupe_key
        db.add(WebOfferAuditItem(run_id=run.id, **data))
    try:
        run.artifact_path = _write_artifact(run, result)
    except OSError as exc:
        run.message = f"Artefaktfehler: {exc}"[:4000]
    db.commit()
    db.refresh(run)
    return run


def _persist_edeka_failure(db: Session, store: Store, period_key: str, error: WebAuditError) -> WebOfferAuditRun:
    run = WebOfferAuditRun(
        store_id=store.id,
        retailer=store.retailer,
        period_key=period_key,
        source_url=EDEKA_OFFERS_ENDPOINT,
        collector_path="edeka_web_offer_api",
        status="failed",
        error_type=error.error_type,
        message=str(error)[:4000],
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        duration_ms=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        run.artifact_path = _write_artifact(run, None, error, error.artifacts)
    except OSError as exc:
        run.message = f"{run.message or ''} Artefaktfehler: {exc}".strip()[:4000]
    db.commit()
    db.refresh(run)
    return run


def run_web_offer_audit(db: Session, store: Store, period_key: str = "current", source_url: str | None = None) -> WebOfferAuditRun:
    if store.retailer != "EDEKA":
        return run_legacy_web_offer_audit(db, store, period_key=period_key, source_url=source_url)
    try:
        result = _fetch_edeka_api(store)
        return _persist_edeka_result(db, store, period_key, result)
    except WebAuditError as exc:
        return _persist_edeka_failure(db, store, period_key, exc)
