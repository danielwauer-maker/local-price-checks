from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
import json
import time

from sqlalchemy.orm import Session

from .aldi_live_collector import is_official_aldi_offer_url, parse_aldi_stationary_chain_offers
from .engine_v140.browser_fetch import browser_fetch
from .engine_v140.collectors import images, visible
from .engine_v140.source_registry import RetailSource
from .models import Store
from .web_offer_audit import WebAuditError, WebAuditResult, WebOfferRecord
from .web_offer_audit_models import WebOfferAuditItem, WebOfferAuditRun
from .web_offer_audit_runtime import _comparison, _write_artifact, filter_period_overlap, quality_deduplicate

ALDI_STATIONARY_OFFERS_URL = "https://www.aldi-sued.de/angebote"


def _as_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%d.%m.%Y").date()
    except ValueError:
        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except ValueError:
            return None


def _packaging_text(quantity, unit) -> str | None:
    if quantity is None or not unit:
        return None
    number = float(quantity)
    display = str(int(number)) if number.is_integer() else str(number).replace(".", ",")
    return f"{display} {unit}"


def _to_web_offer(store: Store, row, source_url: str) -> WebOfferRecord:
    quantity = _as_float(getattr(row, "quantity", None))
    unit = getattr(row, "unit", None)
    return WebOfferRecord(
        retailer="ALDI SÜD",
        store_id=store.id,
        source_url=source_url,
        name=str(getattr(row, "product_name", "") or "").strip(),
        brand=None,
        description=str(getattr(row, "source_text", "") or "").strip() or None,
        price=_as_float(getattr(row, "price", None)),
        old_price=_as_float(getattr(row, "regular_price", None)),
        unit_price=_as_float(getattr(row, "unit_price", None)),
        quantity=_packaging_text(quantity, unit),
        quantity_value=quantity,
        quantity_unit=unit,
        packaging_text=_packaging_text(quantity, unit),
        valid_from=_as_date(getattr(row, "valid_from", None)),
        valid_to=_as_date(getattr(row, "valid_to", None)),
        category=getattr(row, "category", None),
        source_category=getattr(row, "category", None),
        image_url=getattr(row, "image_url", None),
        image_source="aldi_official_chain_page" if getattr(row, "image_url", None) else None,
        image_alt=getattr(row, "image_alt", None),
        provenance={
            "source": "aldi_stationary_chain_page",
            "scope": "regional_chain_stationary",
            "store_specific": False,
            "shared_parser_with_production_collector": True,
            "independent_external_validation": False,
            "note": (
                "Audit of the official stationary ALDI chain surface. Useful for QA/comparison, "
                "but it must not satisfy the independent external-validation gate by itself."
            ),
        },
    )


def fetch_aldi_stationary_chain_audit(
    store: Store,
    *,
    source_url: str = ALDI_STATIONARY_OFFERS_URL,
    fetcher=browser_fetch,
) -> WebAuditResult:
    if store.retailer != "ALDI SÜD":
        raise WebAuditError("endpoint_changed", f"Kein ALDI-SÜD-Audit für {store.retailer}")
    if not is_official_aldi_offer_url(source_url):
        raise WebAuditError("blocked", f"Nicht freigegebene ALDI-SÜD-Quelle: {source_url}")

    started = time.monotonic()
    try:
        try:
            fetched = fetcher(
                source_url,
                timeout_ms=30_000,
                capture_diagnostics=True,
                drain_offer_surface=True,
            )
        except TypeError:
            fetched = fetcher(source_url, timeout_ms=30_000)
    except TimeoutError as exc:
        raise WebAuditError("timeout", str(exc)) from exc
    except Exception as exc:
        low = str(exc).lower()
        kind = "blocked" if "403" in low or "access denied" in low else "browser_required"
        raise WebAuditError(kind, str(exc), dict(getattr(exc, "diagnostics", {}) or {})) from exc

    final_url = fetched.final_url or source_url
    if not is_official_aldi_offer_url(final_url):
        raise WebAuditError("blocked", f"ALDI-Audit wurde auf unerwartete URL umgeleitet: {final_url}")

    html = fetched.content.decode("utf-8", errors="replace")
    source = RetailSource(
        key=f"aldi_web_audit_{store.id}",
        retailer="ALDI SÜD",
        store_name=store.name,
        url=source_url,
        mode="prospect_discovery",
        locality="regional_chain",
        store_specific=False,
        notes="Audit-only ALDI stationary chain source",
    )
    rows = parse_aldi_stationary_chain_offers(
        replace(source, url=final_url),
        visible(html),
        images(html, final_url),
    )
    offers = [_to_web_offer(store, row, final_url) for row in rows]
    offers, duplicates = quality_deduplicate(offers)
    if not offers:
        raise WebAuditError(
            "empty",
            "ALDI SÜD: Die offizielle Angebotsseite enthält keine sicher datierten stationären Wochenangebote.",
            {
                "fetch_mode": fetched.mode,
                "final_url": final_url,
                "response_bytes": len(fetched.content),
            },
        )

    return WebAuditResult(
        offers=offers,
        source_url=source_url,
        final_url=final_url,
        collector_path="aldi_stationary_chain_audit",
        raw_count=len(rows),
        duplicate_count=duplicates,
        message=(
            f"{round((time.monotonic() - started) * 1000)} ms · offizielle ALDI-SÜD-Chain-Quelle; "
            "kein Ersatz für unabhängige externe Validierung"
        ),
        artifacts={
            "fetch_mode": fetched.mode,
            "final_url": final_url,
            "response_bytes": len(fetched.content),
            "scope": "regional_chain_stationary",
            "store_specific": False,
            "independent_external_validation": False,
            "shared_parser_with_production_collector": True,
            "console_errors": list(getattr(fetched, "console_errors", ()) or ()),
            "failed_requests": list(getattr(fetched, "failed_requests", ()) or ()),
        },
    )


def run_aldi_web_offer_audit(
    db: Session,
    store: Store,
    period_key: str = "current",
    source_url: str | None = None,
) -> WebOfferAuditRun:
    url = source_url or ALDI_STATIONARY_OFFERS_URL
    run = WebOfferAuditRun(
        store_id=store.id,
        retailer=store.retailer,
        period_key=period_key,
        source_url=url,
        collector_path="aldi_stationary_chain_audit",
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    started = time.monotonic()
    result = None
    failure = None

    try:
        result = fetch_aldi_stationary_chain_audit(store, source_url=url)
        result.offers = filter_period_overlap(result.offers, period_key, store.retailer)
        result.offers, extra_duplicates = quality_deduplicate(result.offers)
        result.duplicate_count += extra_duplicates
        run.final_url = result.final_url
        run.collector_path = result.collector_path
        run.raw_count = result.raw_count
        run.duplicate_count = result.duplicate_count
        run.valid_count = sum(row.valid for row in result.offers)
        run.missing_price_count = sum(row.price is None for row in result.offers)
        run.missing_image_count = sum(not row.image_url for row in result.offers)
        run.missing_package_count = sum(not row.packaging_text for row in result.offers)
        comparison = _comparison(db, store, result.offers, period_key)
        comparison.update({
            "audit_scope": "regional_chain_stationary",
            "store_specific": False,
            "independent_external_validation": False,
            "external_validation_gate_eligible": False,
            "audit_note": "Shared official ALDI source/parser QA only; independent samples remain required.",
        })
        run.comparison_json = json.dumps(comparison, ensure_ascii=False)
        for row in result.offers:
            data = asdict(row)
            provenance = data.pop("provenance")
            errors = data.pop("validation_errors")
            data["provenance_json"] = json.dumps(provenance, ensure_ascii=False, default=str)
            data["validation_errors"] = ",".join(errors) or None
            data["dedupe_key"] = row.dedupe_key
            db.add(WebOfferAuditItem(run_id=run.id, **data))
        run.status = "success"
        run.message = result.message
    except WebAuditError as exc:
        failure = exc
        run.status = "failed"
        run.error_type = exc.error_type
        run.message = str(exc)[:4000]
    except Exception as exc:
        failure = exc
        run.status = "failed"
        run.error_type = "endpoint_changed"
        run.message = str(exc)[:4000]
    finally:
        run.finished_at = datetime.utcnow()
        run.duration_ms = round((time.monotonic() - started) * 1000)
        try:
            run.artifact_path = _write_artifact(
                run,
                result,
                None if run.status == "success" else failure,
                getattr(failure, "artifacts", None),
            )
        except OSError as exc:
            run.message = f"{run.message or ''} Artefaktfehler: {exc}".strip()[:4000]
        db.commit()
        db.refresh(run)
    return run
