from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from hashlib import sha256
import json
import re
import time

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .clock import app_today
from .config import settings
from .models import MasterProduct, Offer, ProductBarcode, Store
from .web_offer_audit import (
    AldiSuedWebOfferAdapter,
    EdekaWebOfferAdapter,
    LegacyStructuredAdapter,
    NormaWebOfferAdapter,
    PennyWebOfferAdapter,
    ReweWebOfferAdapter,
    NettoWebOfferAdapter,
    WebAuditError,
    WebAuditResult,
    WebOfferRecord,
    _as_date,
    _assert_official_url,
    _clean,
    _date_range,
    _filter_period,
    _fold,
    _largest_image,
    _network_payloads,
    _prices,
    _quantity,
    adapter_for as base_adapter_for,
    normalize_master_key,
)
from .web_offer_audit_models import WebOfferAuditItem, WebOfferAuditRun


# This module is the reviewed execution layer for the admin audit.  It keeps the
# parser library isolated while enforcing the stricter invariants found during
# PR #147 review: same-period comparison, one-to-one matching, store-context
# verification, audit-only surface draining and quality-ranked deduplication.


def period_bounds(period_key: str, today: date | None = None) -> tuple[date, date]:
    if period_key not in {"current", "next"}:
        raise ValueError(f"Unsupported period_key: {period_key}")
    target = today or app_today()
    if period_key == "next":
        target += timedelta(days=7)
    start = target - timedelta(days=target.weekday())
    return start, start + timedelta(days=6)


def offer_overlaps_period(offer: WebOfferRecord, period_key: str) -> bool:
    start, end = period_bounds(period_key)
    offer_start = offer.valid_from or offer.valid_to
    offer_end = offer.valid_to or offer.valid_from
    if offer_start is None and offer_end is None:
        return period_key == "current"
    assert offer_start is not None and offer_end is not None
    return offer_start <= end and offer_end >= start


def filter_period_overlap(offers: list[WebOfferRecord], period_key: str, retailer: str) -> list[WebOfferRecord]:
    dated = [row for row in offers if row.valid_from or row.valid_to]
    if not dated:
        if period_key == "next":
            raise WebAuditError("endpoint_changed", f"{retailer}: nächste Woche ist in der Quelle nicht eindeutig datiert.")
        return offers
    filtered = [row for row in offers if offer_overlaps_period(row, period_key)]
    if not filtered:
        start, _ = period_bounds(period_key)
        raise WebAuditError("empty", f"{retailer}: keine Angebote für ISO-Woche {start.isocalendar().week} gefunden.")
    return filtered


def _offer_quality(offer: WebOfferRecord) -> tuple[int, ...]:
    """Prefer the most complete duplicate instead of blindly preferring images."""
    return (
        int(bool(offer.valid)),
        int(bool(offer.external_product_id or offer.external_offer_id)),
        int(bool(offer.ean)),
        int(offer.price is not None and offer.price > 0),
        int(bool(offer.quantity_value is not None and offer.quantity_unit)),
        int(bool(offer.valid_from)),
        int(bool(offer.valid_to)),
        int(bool(offer.image_url)),
        int(bool(offer.brand)),
        int(bool(offer.description)),
        len(offer.provenance or {}),
    )


def quality_deduplicate(offers: list[WebOfferRecord]) -> tuple[list[WebOfferRecord], int]:
    unique: dict[str, WebOfferRecord] = {}
    for offer in offers:
        offer.validate()
        previous = unique.get(offer.dedupe_key)
        if previous is None or _offer_quality(offer) > _offer_quality(previous):
            unique[offer.dedupe_key] = offer
    return list(unique.values()), len(offers) - len(unique)


def _strong_penny_context_match(store: Store, html: str, payloads: list[dict]) -> bool:
    """Require evidence that regional PENNY data belongs to the requested store.

    A plain appearance of the numeric ID anywhere in a market-finder payload is
    not enough.  We accept an ID only when it is tied to a selected/current
    market/store key, or a selected market element whose text contains the
    requested postcode and city.  If PENNY stops exposing either signal the
    audit fails closed instead of silently attributing another store's offers.
    """
    if not store.external_id:
        return False
    expected_id = str(store.external_id).strip()
    expected_postcode = _fold(store.postal_code)
    expected_city = _fold(store.city)

    serialized = json.dumps(payloads, ensure_ascii=False, default=str)
    id_patterns = (
        rf'(?i)(?:selected|current|active)[^{{}}]{{0,80}}(?:market|store|filial)[^{{}}]{{0,80}}(?:id[^0-9A-Za-z]{{0,8}})?{re.escape(expected_id)}',
        rf'(?i)(?:market|store|filial)(?:Id|ID|_id|id)?[^{{}}]{{0,20}}{re.escape(expected_id)}[^{{}}]{{0,80}}(?:selected|current|active)[^{{}}]{{0,20}}(?:true|1)',
    )
    if any(re.search(pattern, serialized) for pattern in id_patterns):
        return True

    soup = BeautifulSoup(html, "html.parser")
    for element in soup.find_all(True):
        attrs = " ".join(
            [element.get("id") or ""]
            + list(element.get("class") or [])
            + [str(key) for key in element.attrs if key.startswith("data-")]
        ).lower()
        if not any(token in attrs for token in ("market", "store", "filial")):
            continue
        if not any(token in attrs for token in ("selected", "current", "active", "chosen")):
            continue
        values = " ".join(str(value) for value in element.attrs.values())
        text = _fold(f"{values} {element.get_text(' ', strip=True)}")
        if expected_id and expected_id in values:
            return True
        if expected_postcode and expected_city and expected_postcode in text and expected_city in text:
            return True
    return False


def _browser_result_diagnostics(fetched, html: str) -> tuple[list[dict], dict]:
    payloads = _network_payloads(html)
    diagnostics = {
        "html": html,
        "html_sha256": sha256(fetched.content).hexdigest(),
        "response_bytes": len(fetched.content),
        "content_type": fetched.content_type,
        "fetch_mode": fetched.mode,
        "network_payloads": payloads,
        "console_errors": list(getattr(fetched, "console_errors", ()) or ()),
        "failed_requests": list(getattr(fetched, "failed_requests", ()) or ()),
        "screenshot_png": getattr(fetched, "screenshot_png", None),
    }
    return payloads, diagnostics


class ReviewedDirectCollectMixin:
    """Direct browser collector with audit-only deep loading and ranked dedupe."""

    def collect(self, store: Store, source_url: str, period_key: str = "current") -> WebAuditResult:
        started = time.monotonic()
        _assert_official_url(store.retailer, source_url)
        try:
            kwargs = {
                "timeout_ms": settings.collector_timeout_seconds * 1000,
                "capture_diagnostics": True,
                "drain_offer_surface": True,
            }
            try:
                fetched = self.fetcher(source_url, **kwargs)
            except TypeError as exc:
                # Test doubles and older injected fetchers may support only the
                # historic timeout signature.  Do not hide unrelated TypeError.
                if not any(name in str(exc) for name in ("capture_diagnostics", "drain_offer_surface")):
                    raise
                fetched = self.fetcher(source_url, timeout_ms=kwargs["timeout_ms"])
        except TimeoutError as exc:
            raise WebAuditError("timeout", str(exc)) from exc
        except Exception as exc:
            low = str(exc).lower()
            kind = "blocked" if "403" in low or "access denied" in low else "timeout" if "timeout" in low else "browser_required"
            raise WebAuditError(kind, str(exc)) from exc

        html = fetched.content.decode("utf-8", errors="replace")
        _assert_official_url(store.retailer, fetched.final_url or source_url)
        try:
            payloads, diagnostics = _browser_result_diagnostics(fetched, html)
        except WebAuditError as exc:
            exc.artifacts.update({"html": html, "response_bytes": len(fetched.content)})
            raise

        low = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
        if "captcha" in low or "robot or human" in low:
            raise WebAuditError("captcha", "Die Händlerseite fordert ein CAPTCHA; der Audit umgeht es nicht.", diagnostics)
        if "access denied" in low or "zugriff verweigert" in low:
            raise WebAuditError("blocked", "Die Händlerseite blockiert den Browser-Abruf.", diagnostics)

        if store.retailer == "PENNY" and not _strong_penny_context_match(store, html, payloads):
            raise WebAuditError(
                "browser_required",
                f"PENNY-Marktkontext für {store.external_id or 'ohne ID'} / {store.postal_code} {store.city} ist nicht eindeutig nachgewiesen; regionale Angebote werden nicht zugeordnet.",
                diagnostics,
            )

        try:
            raw = self.parse(html, store, fetched.final_url or source_url, period_key)
        except WebAuditError as exc:
            exc.artifacts.update(diagnostics)
            raise
        offers, duplicates = quality_deduplicate(raw)
        if not offers:
            raise WebAuditError("empty", "Keine Angebotsdatensätze auf der erwarteten Händleroberfläche gefunden.", diagnostics)
        return WebAuditResult(
            offers=offers,
            source_url=source_url,
            final_url=fetched.final_url or source_url,
            collector_path=self.collector_path,
            raw_count=len(raw),
            duplicate_count=duplicates,
            message=f"{round((time.monotonic() - started) * 1000)} ms",
            artifacts=diagnostics,
        )


class ReviewedPennyWebOfferAdapter(ReviewedDirectCollectMixin, PennyWebOfferAdapter):
    pass


class ReviewedAldiSuedWebOfferAdapter(ReviewedDirectCollectMixin, AldiSuedWebOfferAdapter):
    def collect(self, store: Store, source_url: str, period_key: str = "current") -> WebAuditResult:
        _assert_official_url(store.retailer, source_url)
        if not store.external_id:
            raise WebAuditError("browser_required", "ALDI SÜD benötigt eine verifizierte servicePoint-/Filial-ID.")
        if period_key == "next":
            raise WebAuditError("endpoint_changed", "ALDI SÜD: Ein separater Endpoint für die nächste Woche ist noch nicht belastbar nachgewiesen.")
        return ReviewedDirectCollectMixin.collect(self, store, source_url, period_key)


class ReviewedNormaWebOfferAdapter(ReviewedDirectCollectMixin, NormaWebOfferAdapter):
    """Keep NORMA navigation behavior but use reviewed direct collection per page."""

    def collect(self, store: Store, source_url: str, period_key: str = "current") -> WebAuditResult:
        initial = ReviewedDirectCollectMixin.collect(self, store, source_url, period_key)
        links = self._dated_links(str(initial.artifacts.get("html") or ""), initial.final_url)
        target_start, _ = period_bounds(period_key)
        target_iso = target_start.isocalendar()[:2]
        selected = [url for url, day in links.items() if day.isocalendar()[:2] == target_iso]
        if period_key == "next" and not selected:
            raise WebAuditError("empty", "NORMA-Navigation enthält noch keinen nächsten Angebotszeitraum.", initial.artifacts)
        results = [initial] if initial.final_url in selected else []
        for url in selected:
            if url == initial.final_url or len(results) >= 7:
                continue
            results.append(ReviewedDirectCollectMixin.collect(self, store, url, period_key))
        if not results:
            raise WebAuditError("empty", f"NORMA-Navigation enthält keine Seiten für ISO-Woche {target_iso[1]}.", initial.artifacts)
        rows = [offer for result in results for offer in result.offers]
        offers, duplicates = quality_deduplicate(rows)
        diagnostics = dict(initial.artifacts)
        diagnostics["selected_period_urls"] = selected
        return WebAuditResult(
            offers=offers,
            source_url=source_url,
            final_url=initial.final_url,
            collector_path=self.collector_path,
            raw_count=sum(result.raw_count for result in results),
            duplicate_count=sum(result.duplicate_count for result in results) + duplicates,
            artifacts=diagnostics,
            message=f"{len(results)} dynamisch aus der Navigation ermittelte Zeitraumseite(n)",
        )


def _first_price_from_selector(card, selectors: tuple[str, ...]) -> float | None:
    for selector in selectors:
        for node in card.select(selector):
            values = _prices(_clean(node.get_text(" ", strip=True)))
            if values:
                return values[0]
    return None


def _edeka_price_fields(card, text: str) -> tuple[float | None, float | None, float | None]:
    """Extract sale/regular/base price by semantics before numeric fallback."""
    sale = _first_price_from_selector(card, (
        "[class*='offer-price' i]", "[class*='angebotspreis' i]", "[class*='price__value' i]",
        "[data-testid*='offer-price' i]", "[aria-label*='Festpreis' i]",
    ))
    old = _first_price_from_selector(card, (
        "[class*='old-price' i]", "[class*='regular-price' i]", "[class*='strike' i]", "[class*='statt' i]",
    ))
    unit = _first_price_from_selector(card, (
        "[class*='base-price' i]", "[class*='unit-price' i]", "[class*='grundpreis' i]",
    ))

    if sale is None:
        for pattern in (
            r"(?i)Festpreis\s+von\s+(\d{1,3}[.,]\d{2})",
            r"(?i)(?:Angebotspreis|Aktionspreis)\D{0,20}(\d{1,3}[.,]\d{2})",
            r"(?i)\bnur\s+(\d{1,3}[.,]\d{2})",
        ):
            match = re.search(pattern, text)
            if match:
                sale = float(match.group(1).replace(",", "."))
                break

    if old is None:
        match = re.search(r"(?i)(?:statt|bisher|uvp)\D{0,12}(\d{1,3}[.,]\d{2})", text)
        if match:
            old = float(match.group(1).replace(",", "."))
    if unit is None:
        match = re.search(
            r"(?i)(?:1\s*(?:kg|l)|100\s*(?:g|ml))\s*=\s*(\d{1,3}[.,]\d{2})",
            text,
        )
        if match:
            unit = float(match.group(1).replace(",", "."))

    if sale is None:
        all_prices = [value for value in _prices(text) if value > 0]
        excluded = {value for value in (old, unit) if value is not None}
        candidates = [value for value in all_prices if value not in excluded]
        if candidates:
            # For a regular-price/offer-price card the promotional price is
            # normally the lower non-unit amount.  Semantic selectors above
            # remain authoritative and avoid choosing a base price.
            sale = min(candidates) if old is not None else candidates[0]
    if old is not None and sale is not None and old <= sale:
        old = None
    return sale, old, unit


class ReviewedEdekaWebOfferAdapter(ReviewedDirectCollectMixin, EdekaWebOfferAdapter):
    def parse(self, html: str, store: Store, source_url: str, period_key: str) -> list[WebOfferRecord]:
        soup = BeautifulSoup(html, "html.parser")
        page_text = _clean(soup.get_text(" ", strip=True))
        page_dates: list[date] = []
        date_re = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")
        for match in date_re.finditer(page_text):
            parsed = _as_date(".".join(match.groups()))
            if parsed and parsed not in page_dates:
                page_dates.append(parsed)
        page_from = min(page_dates) if page_dates else None
        page_to = max(page_dates) if page_dates else None

        offers: list[WebOfferRecord] = []
        for card in soup.select("article"):
            text = _clean(card.get_text(" ", strip=True))
            image = card.find("img")
            name, brand = self._name_brand(card, image)
            if not name or len(name) > 300:
                continue
            sale, old, unit_price = _edeka_price_fields(card, text)
            quantity, q_value, q_unit = _quantity(text)
            image_candidates = []
            if image:
                for attribute in ("src", "data-src", "data-lazy-src"):
                    if image.get(attribute):
                        from urllib.parse import urljoin
                        image_candidates.append((urljoin(source_url, image.get(attribute)), _clean(image.get("alt")) or None, 0))
                for srcset in (image.get("srcset"), image.get("data-srcset")):
                    from urllib.parse import urljoin
                    for candidate in (srcset or "").split(","):
                        parts = candidate.strip().split()
                        if not parts:
                            continue
                        score = int(re.sub(r"\D", "", parts[1])) if len(parts) > 1 and re.search(r"\d", parts[1]) else 0
                        image_candidates.append((urljoin(source_url, parts[0]), _clean(image.get("alt")) or None, score))
            image_url, image_alt = _largest_image(image_candidates)
            date_evidence = f"{text} {_clean(image.get('alt')) if image else ''}"
            dates = [_as_date(".".join(match.groups())) for match in date_re.finditer(date_evidence)]
            dates = [value for value in dates if value]
            range_from, range_to = _date_range(date_evidence)
            offer_link = card.find("a", href=re.compile(r"#?(?:angebot|offer)-", re.I))
            external_offer_id = _clean(card.get("data-offer-id") or card.get("id")) or None
            if not external_offer_id and offer_link:
                external_offer_id = _clean(offer_link.get("href")).lstrip("#") or None
            if sale is None and not external_offer_id:
                continue
            offers.append(WebOfferRecord(
                retailer=self.retailer,
                store_id=store.id,
                source_url=source_url,
                external_offer_id=external_offer_id,
                name=name,
                brand=brand,
                price=sale,
                old_price=old,
                unit_price=unit_price,
                quantity=quantity,
                quantity_value=q_value,
                quantity_unit=q_unit,
                packaging_text=quantity,
                valid_from=range_from or (dates[0] if dates else page_from),
                valid_to=range_to or (dates[1] if len(dates) > 1 else page_to),
                image_url=image_url,
                image_source="retailer_page" if image_url else None,
                image_alt=image_alt,
                provenance={"element": card.name, "classes": card.get("class", []), "text": text[:2000], "price_parser": "edeka_semantic_v2"},
            ))
        return filter_period_overlap(offers, period_key, self.retailer)


def adapter_for(retailer: str):
    normalized = _fold(retailer)
    if normalized == "penny":
        return ReviewedPennyWebOfferAdapter()
    if normalized == "edeka":
        return ReviewedEdekaWebOfferAdapter()
    if normalized == "aldi sud":
        return ReviewedAldiSuedWebOfferAdapter()
    if normalized == "norma":
        return ReviewedNormaWebOfferAdapter()
    # REWE and Netto deliberately keep the proven legacy structured collector.
    return base_adapter_for(retailer)


def _all_barcodes(db: Session) -> dict[int, set[str]]:
    values: dict[int, set[str]] = {}
    for product_id, barcode in db.query(ProductBarcode.master_product_id, ProductBarcode.barcode).all():
        values.setdefault(product_id, set()).add(barcode)
    return values


def _comparison(db: Session, store: Store, offers: list[WebOfferRecord], period_key: str) -> dict[str, int | str]:
    period_start, period_end = period_bounds(period_key)
    web_rows = [row for row in offers if row.valid]
    web_by_key = {row.dedupe_key: row for row in web_rows}
    prospect_rows = (
        db.query(Offer, MasterProduct)
        .join(MasterProduct, MasterProduct.id == Offer.master_product_id)
        .filter(
            Offer.store_id == store.id,
            Offer.valid_from <= period_end,
            Offer.valid_to >= period_start,
        )
        .all()
    )
    barcodes = _all_barcodes(db)
    used_web: set[str] = set()
    matched_pairs = 0
    price_match = price_mismatch = quantity_match = quantity_mismatch = image_available = 0
    fuzzy_hint_count = 0

    def available(rows):
        return [row for row in rows if row.dedupe_key not in used_web]

    for prospect, product in prospect_rows:
        exact = normalize_master_key(
            " ".join(filter(None, (product.brand, product.name))),
            *_quantity(product.package_size)[1:],
        )
        family = normalize_master_key(" ".join(filter(None, (product.brand, product.name))))
        match = None
        product_barcodes = barcodes.get(product.id, set())
        if product_barcodes:
            match = next((row for row in available(web_rows) if row.ean and row.ean in product_barcodes), None)
        if not match:
            match = next((
                row for row in available(web_rows)
                if normalize_master_key(
                    " ".join(filter(None, (row.brand, row.name))), row.quantity_value, row.quantity_unit
                ) == exact
            ), None)
        if not match:
            family_candidates = [
                row for row in available(web_rows)
                if normalize_master_key(" ".join(filter(None, (row.brand, row.name)))) == family
            ]
            match = family_candidates[0] if len(family_candidates) == 1 else None
        if not match:
            best = max((SequenceMatcher(None, family, normalize_master_key(row.name)).ratio() for row in available(web_rows)), default=0)
            fuzzy_hint_count += int(best >= 0.82)
            continue

        used_web.add(match.dedupe_key)
        matched_pairs += 1
        if match.price is not None and abs(match.price - prospect.price) < 0.005:
            price_match += 1
        else:
            price_mismatch += 1
        expected_package = _fold(product.package_size)
        actual_package = _fold(match.packaging_text)
        if expected_package and actual_package and expected_package == actual_package:
            quantity_match += 1
        elif expected_package or actual_package:
            quantity_mismatch += 1
        if match.image_url:
            image_available += 1

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "prospect_count": len(prospect_rows),
        "web_count": len(web_by_key),
        "matched": matched_pairs,
        "web_only": max(len(web_by_key) - matched_pairs, 0),
        "prospect_only": max(len(prospect_rows) - matched_pairs, 0),
        "price_match": price_match,
        "price_mismatch": price_mismatch,
        "quantity_match": quantity_match,
        "quantity_mismatch": quantity_mismatch,
        "image_available": image_available,
        "fuzzy_hint_count": fuzzy_hint_count,
    }


def _write_artifact(run: WebOfferAuditRun, result: WebAuditResult | None, error: Exception | None = None, diagnostics: dict | None = None) -> str:
    root = settings.data_dir / "diagnostics" / "web_offer_audit" / str(run.store_id)
    root.mkdir(parents=True, exist_ok=True)
    prefix = f"run-{run.id}-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    path = root / f"{prefix}.json"
    evidence = diagnostics or (result.artifacts if result else {})
    network_payloads = evidence.get("network_payloads") if isinstance(evidence.get("network_payloads"), list) else []
    payload = {
        "run_id": run.id,
        "store_id": run.store_id,
        "retailer": run.retailer,
        "source_url": run.source_url,
        "status": run.status,
        "error_type": run.error_type,
        "message": str(error or run.message or ""),
        "raw_response_metadata": {
            "html_sha256": evidence.get("html_sha256"),
            "response_bytes": evidence.get("response_bytes"),
            "content_type": evidence.get("content_type"),
            "fetch_mode": evidence.get("fetch_mode"),
            "network_response_count": len(network_payloads),
            "network_urls": [_clean(row.get("url")) for row in network_payloads[:100] if isinstance(row, dict)],
            "console_errors": list(evidence.get("console_errors") or [])[:100],
            "failed_requests": list(evidence.get("failed_requests") or [])[:100],
        },
        "result": {
            "raw_count": result.raw_count,
            "duplicate_count": result.duplicate_count,
            "offers": [
                {
                    **asdict(row),
                    "valid_from": str(row.valid_from) if row.valid_from else None,
                    "valid_to": str(row.valid_to) if row.valid_to else None,
                    "collected_at": row.collected_at.isoformat(),
                }
                for row in result.offers[:1000]
            ],
        } if result else None,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if error:
        html = evidence.get("html")
        if isinstance(html, str):
            (root / f"{prefix}.html").write_text(html[:2_000_000], encoding="utf-8")
        if network_payloads:
            bounded = []
            for row in network_payloads:
                candidate = bounded + [row]
                if len(json.dumps(candidate, ensure_ascii=False, default=str)) > 1_900_000:
                    break
                bounded = candidate
            (root / f"{prefix}.network.json").write_text(json.dumps(bounded, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        screenshot = evidence.get("screenshot_png")
        if isinstance(screenshot, bytes) and screenshot:
            (root / f"{prefix}.png").write_bytes(screenshot[:5_000_000])
    manifests = sorted(root.glob("run-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in manifests[20:]:
        for companion in root.glob(f"{stale.stem}.*"):
            companion.unlink(missing_ok=True)
    return str(path)


def run_web_offer_audit(db: Session, store: Store, period_key: str = "current", source_url: str | None = None) -> WebOfferAuditRun:
    url = _clean(source_url or store.source_url)
    if not url.startswith(("https://", "http://")):
        raise ValueError("Der Markt hat keine gültige offizielle Quell-URL.")
    adapter = adapter_for(store.retailer)
    run = WebOfferAuditRun(
        store_id=store.id,
        retailer=store.retailer,
        period_key=period_key,
        source_url=url,
        collector_path=adapter.collector_path,
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    started = time.monotonic()
    result = None
    failure = None
    try:
        result = adapter.collect(store, url, period_key)
        # Legacy adapters may already have deduplicated their parser output;
        # applying the ranked pass is idempotent and protects future adapters.
        result.offers, extra_duplicates = quality_deduplicate(result.offers)
        result.duplicate_count += extra_duplicates
        run.final_url = result.final_url
        run.raw_count = result.raw_count
        run.duplicate_count = result.duplicate_count
        run.valid_count = sum(row.valid for row in result.offers)
        run.missing_price_count = sum(row.price is None for row in result.offers)
        run.missing_image_count = sum(not row.image_url for row in result.offers)
        run.missing_package_count = sum(not row.packaging_text for row in result.offers)
        comparison = _comparison(db, store, result.offers, period_key)
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
