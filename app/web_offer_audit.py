from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
import httpx
from sqlalchemy.orm import Session

from .config import settings
from .clock import app_today
from .engine_v140.browser_fetch import BrowserFetchResult, browser_fetch
from .engine_v140.collectors import collect_one
from .engine_v140.source_registry import RetailSource
from .extractor_adapter import normalize_master_key
from .models import MasterProduct, Offer, ProductBarcode, Store
from .prospect_models import OfferProvenance, ProspectArchive
from .web_offer_audit_models import WebOfferAuditItem, WebOfferAuditRun


SUPPORTED_RETAILERS = ("REWE", "Netto Marken-Discount", "EDEKA", "PENNY", "ALDI SÜD", "NORMA")
ERROR_TYPES = {"blocked", "captcha", "browser_required", "endpoint_changed", "timeout", "invalid_json", "empty"}
_RETAILER_HOSTS = {
    "rewe": ("rewe.de",),
    "netto marken discount": ("netto-online.de",),
    "netto": ("netto-online.de",),
    "edeka": ("edeka.de",),
    "penny": ("penny.de",),
    "aldi sud": ("aldi-sued.de",),
    "norma": ("norma-online.de",),
}
_PLACEHOLDER_IMAGE = re.compile(r"(?:placeholder|dummy|spacer|tracking|pixel|logo|favicon|hero|banner)", re.I)
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")
_DATE_RANGE = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(?:(\d{2,4}))?\s*(?:bis|[-–])\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})",
    re.I,
)
_QUANTITY = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(kg|g|l|ml|stück|stk\.?|pack|becher|dose|flasche)\b", re.I)
_PRICE = re.compile(r"(?<!\d)(\d{1,3}[.,]\d{2})(?!\d)")
_INTEGER_PRICE = re.compile(r"(?<!\d)(\d{1,3})[.,]\s*[–-](?!\d)")


class WebAuditError(RuntimeError):
    def __init__(self, error_type: str, message: str, artifacts: dict | None = None):
        super().__init__(message)
        self.error_type = error_type if error_type in ERROR_TYPES else "endpoint_changed"
        self.artifacts = artifacts or {}


@dataclass
class WebOfferRecord:
    retailer: str
    store_id: int
    source_url: str
    name: str
    source_type: str = "web"
    external_offer_id: str | None = None
    external_product_id: str | None = None
    ean: str | None = None
    brand: str | None = None
    description: str | None = None
    price: float | None = None
    old_price: float | None = None
    discount_text: str | None = None
    unit_price: float | None = None
    quantity: str | None = None
    quantity_value: float | None = None
    quantity_unit: str | None = None
    packaging_text: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    category: str | None = None
    source_category: str | None = None
    image_url: str | None = None
    image_source: str | None = None
    image_alt: str | None = None
    collected_at: datetime = field(default_factory=datetime.utcnow)
    provenance: dict = field(default_factory=dict)
    valid: bool = True
    validation_errors: list[str] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        if self.external_offer_id:
            return f"offer:{self.external_offer_id}"[:420]
        if self.external_product_id:
            return f"product:{self.external_product_id}:{self.valid_from}:{self.price}"[:420]
        return f"normalized:{normalize_master_key(self.name, self.quantity_value, self.quantity_unit)}:{self.valid_from}:{self.price}"[:420]

    def validate(self) -> "WebOfferRecord":
        errors: list[str] = []
        self.name = _clean(self.name)
        if len(self.name) < 2:
            errors.append("missing_name")
        if self.price is None or self.price <= 0:
            errors.append("missing_price")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            errors.append("invalid_dates")
        if self.image_url and not valid_product_image(self.image_url):
            self.image_url = None
            self.image_source = None
            errors.append("invalid_image")
        self.validation_errors = sorted(set(self.validation_errors + errors))
        self.valid = not any(error in {"missing_name", "missing_price", "invalid_dates"} for error in self.validation_errors)
        return self


@dataclass
class WebAuditResult:
    offers: list[WebOfferRecord]
    source_url: str
    final_url: str
    collector_path: str
    raw_count: int
    duplicate_count: int = 0
    status: str = "success"
    message: str | None = None
    artifacts: dict = field(default_factory=dict)


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


def _fold(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", _clean(value).lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _assert_official_url(retailer: str, url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    allowed = _RETAILER_HOSTS.get(_fold(retailer), ())
    if parsed.scheme != "https" or not any(hostname == host or hostname.endswith(f".{host}") for host in allowed):
        raise WebAuditError("blocked", f"Nicht freigegebene Händler-URL für {retailer}: {hostname or 'ohne Host'}")


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        # Some retailer APIs expose prices in cents.
        return number / 100 if number >= 1000 and float(number).is_integer() else number
    raw = _clean(value)
    if "," in raw and "." in raw and raw.rfind(",") > raw.rfind("."):
        raw = raw.replace(".", "")
    match = _PRICE.search(raw)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _prices(value: str) -> list[float]:
    found = [(match.start(), float(match.group(1).replace(",", "."))) for match in _PRICE.finditer(value)]
    found.extend((match.start(), float(match.group(1))) for match in _INTEGER_PRICE.finditer(value))
    return [price for _, price in sorted(found)]


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    raw = _clean(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except ValueError:
        pass
    match = _DATE.search(raw)
    if not match:
        return None
    year = int(match.group(3))
    if year < 100:
        year += 2000
    try:
        return date(year, int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def _date_range(value: str) -> tuple[date | None, date | None]:
    match = _DATE_RANGE.search(value or "")
    if not match:
        return None, None
    end_year = int(match.group(6))
    if end_year < 100:
        end_year += 2000
    start_year = int(match.group(3)) if match.group(3) else end_year
    if start_year < 100:
        start_year += 2000
    try:
        return (
            date(start_year, int(match.group(2)), int(match.group(1))),
            date(end_year, int(match.group(5)), int(match.group(4))),
        )
    except ValueError:
        return None, None


def _quantity(value: object) -> tuple[str | None, float | None, str | None]:
    text = _clean(value)
    match = _QUANTITY.search(text)
    if not match:
        return (text or None, None, None)
    return text, float(match.group(1).replace(",", ".")), match.group(2).lower().rstrip(".")


def valid_product_image(url: str | None) -> bool:
    if not url or url.startswith("data:") or _PLACEHOLDER_IMAGE.search(url):
        return False
    parsed = urlparse(url)
    known_image_host = parsed.netloc.lower().startswith("offer-images.api.edeka")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and (
        known_image_host or bool(re.search(r"\.(?:avif|jpe?g|png|webp)(?:[?#]|$)", parsed.path, re.I))
    )


def _largest_image(candidates: list[tuple[str, str | None, int]]) -> tuple[str | None, str | None]:
    safe = [item for item in candidates if valid_product_image(item[0])]
    if not safe:
        return None, None
    url, alt, _ = max(safe, key=lambda item: item[2])
    return url, alt


def deduplicate(offers: list[WebOfferRecord]) -> tuple[list[WebOfferRecord], int]:
    unique: dict[str, WebOfferRecord] = {}
    for offer in offers:
        offer.validate()
        previous = unique.get(offer.dedupe_key)
        if previous is None or (not previous.image_url and offer.image_url):
            unique[offer.dedupe_key] = offer
    return list(unique.values()), len(offers) - len(unique)


def _filter_period(offers: list[WebOfferRecord], period_key: str, retailer: str) -> list[WebOfferRecord]:
    target = app_today() if period_key == "current" else app_today() + timedelta(days=7)
    target_iso = target.isocalendar()[:2]
    dated = [row for row in offers if row.valid_from]
    if not dated:
        if period_key == "next":
            raise WebAuditError("endpoint_changed", f"{retailer}: nächste Woche ist in der Quelle nicht eindeutig datiert.")
        return offers
    filtered = [row for row in offers if row.valid_from and row.valid_from.isocalendar()[:2] == target_iso]
    if not filtered:
        raise WebAuditError("empty", f"{retailer}: keine Angebote für ISO-Woche {target_iso[1]} gefunden.")
    return filtered


def compare_regional_offer_sets(left: list[WebOfferRecord], right: list[WebOfferRecord]) -> dict[str, int | float]:
    """Compare two store snapshots without claiming national equivalence."""
    left_rows = {row.external_product_id or row.external_offer_id or normalize_master_key(row.name, row.quantity_value, row.quantity_unit): row for row in left}
    right_rows = {row.external_product_id or row.external_offer_id or normalize_master_key(row.name, row.quantity_value, row.quantity_unit): row for row in right}
    shared = set(left_rows) & set(right_rows)
    union = set(left_rows) | set(right_rows)
    return {
        "left_count": len(left_rows), "right_count": len(right_rows), "shared": len(shared),
        "left_only": len(set(left_rows) - shared), "right_only": len(set(right_rows) - shared),
        "jaccard": round(len(shared) / len(union), 4) if union else 1.0,
        "price_differences": sum(
            1 for key in shared
            if left_rows[key].price is not None and right_rows[key].price is not None
            and abs(left_rows[key].price - right_rows[key].price) >= 0.005
        ),
        "validity_differences": sum(
            1 for key in shared
            if (left_rows[key].valid_from, left_rows[key].valid_to) != (right_rows[key].valid_from, right_rows[key].valid_to)
        ),
    }


def _network_payloads(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="lpc-network-json")
    if not script:
        return []
    try:
        value = json.loads(script.get_text() or "[]")
    except json.JSONDecodeError as exc:
        raise WebAuditError("invalid_json", f"Ungültiger Netzwerk-JSON-Snapshot: {exc}") from exc
    return value if isinstance(value, list) else []


def _iter_dicts(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _first(row: dict, *names: str):
    for name in names:
        value = row.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def _dict_offer(row: dict, retailer: str, store_id: int, source_url: str, category: str | None = None) -> WebOfferRecord | None:
    name = _first(row, "title", "name", "productName", "product_name", "descriptionShort")
    raw_price = _first(row, "price", "sellingPrice", "offerPrice", "currentPrice", "benefitPrice")
    if isinstance(raw_price, dict):
        raw_price = _first(raw_price, "value", "amount", "price", "centAmount")
    price = _number(raw_price)
    if retailer == "ALDI SÜD" and isinstance(raw_price, int):
        price = raw_price / 100
    if not name or price is None:
        return None
    raw_quantity = _first(row, "quantity", "sellingSize", "packageSize", "content", "bundleText")
    quantity, quantity_value, quantity_unit = _quantity(raw_quantity)
    assets = _first(row, "images", "assets", "image", "media") or []
    candidates: list[tuple[str, str | None, int]] = []
    for asset in _iter_dicts(assets):
        image = _first(asset, "url", "src", "imageUrl", "href")
        if image:
            width = int(_first(asset, "width", "w") or 0)
            height = int(_first(asset, "height", "h") or 0)
            candidates.append((urljoin(source_url, str(image)), _clean(_first(asset, "alt", "title")) or None, width * height))
    if isinstance(assets, str):
        candidates.append((urljoin(source_url, assets), None, 0))
    image_url, image_alt = _largest_image(candidates)
    product_data = row.get("productData") if isinstance(row.get("productData"), dict) else {}
    return WebOfferRecord(
        retailer=retailer,
        store_id=store_id,
        source_url=source_url,
        external_offer_id=_clean(_first(row, "offerId", "offerID", "id", "uuid")) or None,
        external_product_id=_clean(_first(row, "sku", "productId", "productID") or _first(product_data, "id", "uuid", "sku")) or None,
        ean=_clean(_first(row, "ean", "gtin") or _first(product_data, "ean", "gtin")) or None,
        name=_clean(name),
        brand=_clean(_first(row, "brand", "manufacturer")) or None,
        description=_clean(_first(row, "description", "subtitle", "text")) or None,
        price=price,
        old_price=_number(_first(row, "listPrice", "oldPrice", "regularPrice", "strikePrice")),
        discount_text=_clean(_first(row, "discountText", "badge", "promotionText")) or None,
        unit_price=_number(_first(row, "basePrice", "unitPrice")),
        quantity=quantity,
        quantity_value=quantity_value,
        quantity_unit=quantity_unit,
        packaging_text=_clean(_first(row, "packagingText", "bundleText", "sellingSize")) or quantity,
        valid_from=_as_date(_first(row, "validFrom", "startDate", "dateFrom")),
        valid_to=_as_date(_first(row, "validTo", "endDate", "dateTo")),
        category=_clean(_first(row, "category", "categoryName")) or category,
        source_category=category,
        image_url=image_url,
        image_source="retailer_api" if image_url else None,
        image_alt=image_alt,
        provenance={"keys": sorted(row.keys())[:80]},
    )


class RetailerWebOfferAdapter(ABC):
    retailer: str
    collector_path: str

    def __init__(self, fetcher=browser_fetch, max_pages: int = 40):
        self.fetcher = fetcher
        self.max_pages = max_pages

    def collect(self, store: Store, source_url: str, period_key: str = "current") -> WebAuditResult:
        started = time.monotonic()
        _assert_official_url(store.retailer, source_url)
        try:
            try:
                fetched = self.fetcher(
                    source_url, timeout_ms=settings.collector_timeout_seconds * 1000, capture_diagnostics=True
                )
            except TypeError as exc:
                # Small injected test fetchers and existing custom integrations
                # may predate the optional diagnostic keyword.
                if "capture_diagnostics" not in str(exc):
                    raise
                fetched = self.fetcher(source_url, timeout_ms=settings.collector_timeout_seconds * 1000)
        except TimeoutError as exc:
            raise WebAuditError("timeout", str(exc)) from exc
        except Exception as exc:
            low = str(exc).lower()
            kind = "blocked" if "403" in low or "access denied" in low else "timeout" if "timeout" in low else "browser_required"
            raise WebAuditError(kind, str(exc)) from exc
        html = fetched.content.decode("utf-8", errors="replace")
        _assert_official_url(store.retailer, fetched.final_url or source_url)
        payloads = []
        try:
            payloads = _network_payloads(html)
        except WebAuditError:
            # Keep invalid JSON in the bounded HTML snapshot; parsing below
            # reports the explicit invalid_json status.
            pass
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
        low = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
        if "captcha" in low or "robot or human" in low:
            raise WebAuditError("captcha", "Die Händlerseite fordert ein CAPTCHA; der Audit umgeht es nicht.", diagnostics)
        if "access denied" in low or "zugriff verweigert" in low:
            raise WebAuditError("blocked", "Die Händlerseite blockiert den Browser-Abruf.", diagnostics)
        try:
            raw = self.parse(html, store, fetched.final_url or source_url, period_key)
        except WebAuditError as exc:
            exc.artifacts.update(diagnostics)
            raise
        offers, duplicates = deduplicate(raw)
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

    @abstractmethod
    def parse(self, html: str, store: Store, source_url: str, period_key: str) -> list[WebOfferRecord]:
        raise NotImplementedError


class NetworkJsonAdapter(RetailerWebOfferAdapter):
    category_url_markers: tuple[str, ...] = ()

    def parse(self, html: str, store: Store, source_url: str, period_key: str) -> list[WebOfferRecord]:
        offers: list[WebOfferRecord] = []
        seen_pages: set[str] = set()
        payloads = _network_payloads(html)
        for payload in payloads:
            url = _clean(payload.get("url"))
            if url in seen_pages or not any(marker in url.lower() for marker in self.category_url_markers):
                continue
            if len(seen_pages) >= self.max_pages:
                break
            seen_pages.add(url)
            if "dauerhaft" in url.lower():
                continue
            source_category = url.rstrip("/").split("/")[-1].split("?")[0]
            for row in _iter_dicts(payload.get("data")):
                offer = _dict_offer(row, self.retailer, store.id, source_url, source_category)
                if offer:
                    offer.provenance["network_url"] = url
                    offers.append(offer)
        return offers


class PennyWebOfferAdapter(NetworkJsonAdapter):
    retailer = "PENNY"
    collector_path = "penny_rest_offer_tiles"
    category_url_markers = ("/.rest/offers/by-category/",)

    def parse(self, html: str, store: Store, source_url: str, period_key: str) -> list[WebOfferRecord]:
        offers = super().parse(html, store, source_url, period_key)
        target = app_today() if period_key == "current" else app_today() + timedelta(days=7)
        target_year, target_week, _ = target.isocalendar()
        filtered = []
        for offer in offers:
            category_url = _clean(offer.provenance.get("network_url"))
            match = re.search(r"/by-category/(\d{4})-(\d{1,2})/", category_url)
            if not match or (int(match.group(1)), int(match.group(2))) == (target_year, target_week):
                filtered.append(offer)
        return filtered


class AldiSuedWebOfferAdapter(NetworkJsonAdapter):
    retailer = "ALDI SÜD"
    collector_path = "aldi_product_search_api"
    category_url_markers = ("/v3/product-search",)

    def __init__(self, fetcher=browser_fetch, max_pages: int = 40, page_fetcher=None):
        super().__init__(fetcher=fetcher, max_pages=max_pages)
        self.page_fetcher = page_fetcher or self._fetch_json

    @staticmethod
    def _fetch_json(url: str) -> dict:
        last_error = None
        for attempt in range(3):
            try:
                response = httpx.get(
                    url, follow_redirects=True, timeout=settings.collector_timeout_seconds,
                    headers={"Accept": "application/json", "User-Agent": "Spareno-Web-Audit/1.0"},
                )
                if response.status_code in {401, 403, 429}:
                    raise WebAuditError("blocked", f"ALDI API antwortet mit HTTP {response.status_code}")
                response.raise_for_status()
                return response.json()
            except WebAuditError:
                raise
            except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.2 * (attempt + 1))
        kind = "timeout" if isinstance(last_error, httpx.TimeoutException) else "endpoint_changed"
        raise WebAuditError(kind, f"ALDI API-Seite konnte nicht gelesen werden: {last_error}")

    @staticmethod
    def _url_with_offset(url: str, offset: int, limit: int) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query["offset"] = [str(offset)]
        query["limit"] = [str(limit)]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    def parse(self, html: str, store: Store, source_url: str, period_key: str) -> list[WebOfferRecord]:
        payloads = _network_payloads(html)
        matching = []
        for payload in payloads:
            url = _clean(payload.get("url"))
            if "/v3/product-search" not in url.lower():
                continue
            service_point = (parse_qs(urlparse(url).query).get("servicePoint") or [""])[0]
            if service_point == store.external_id:
                matching.append(payload)
        if not matching:
            raise WebAuditError(
                "browser_required",
                f"ALDI Browserkontext enthält nicht die erwartete servicePoint-ID {store.external_id}; fremde Filialdaten werden nicht übernommen.",
            )

        first_url = _clean(matching[0].get("url"))
        _assert_official_url(store.retailer, first_url)
        first_data = matching[0].get("data") if isinstance(matching[0].get("data"), dict) else {}
        meta = first_data.get("meta") if isinstance(first_data.get("meta"), dict) else {}
        pagination = meta.get("pagination") if isinstance(meta.get("pagination"), dict) else {}
        total = int(pagination.get("totalCount") or 0)
        first_rows = first_data.get("data") if isinstance(first_data.get("data"), list) else []
        limit = max(len(first_rows), int((parse_qs(urlparse(first_url).query).get("limit") or [12])[0]), 1)
        captured_offsets = {
            int((parse_qs(urlparse(_clean(payload.get("url"))).query).get("offset") or [0])[0])
            for payload in matching
        }
        offset = limit
        pages = len(matching)
        while total and offset < total and pages < self.max_pages:
            if offset not in captured_offsets:
                page_url = self._url_with_offset(first_url, offset, limit)
                matching.append({"url": page_url, "data": self.page_fetcher(page_url)})
                pages += 1
            offset += limit

        synthetic = BeautifulSoup(html, "html.parser")
        old = synthetic.find("script", id="lpc-network-json")
        if old:
            old.string = json.dumps(matching, ensure_ascii=False).replace("</script>", "<\\/script>")
        return super().parse(str(synthetic), store, source_url, period_key)

    def collect(self, store: Store, source_url: str, period_key: str = "current") -> WebAuditResult:
        _assert_official_url(store.retailer, source_url)
        if not store.external_id:
            raise WebAuditError("browser_required", "ALDI SÜD benötigt eine verifizierte servicePoint-/Filial-ID.")
        if period_key == "next":
            raise WebAuditError("endpoint_changed", "ALDI SÜD: Ein separater Endpoint für die nächste Woche ist noch nicht belastbar nachgewiesen.")
        return super().collect(store, source_url, period_key)


class LegacyStructuredAdapter(RetailerWebOfferAdapter):
    """Audit-only bridge around the proven structured parser; no import call."""

    def parse(self, html: str, store: Store, source_url: str, period_key: str) -> list[WebOfferRecord]:
        raise NotImplementedError

    def _validate_result(self, store: Store, result: dict, source_url: str) -> None:
        return None

    def collect(self, store: Store, source_url: str, period_key: str = "current") -> WebAuditResult:
        _assert_official_url(store.retailer, source_url)
        source = RetailSource(
            key=f"web_audit_{store.id}", retailer=store.retailer, store_name=store.name,
            url=source_url, mode="store_page", locality="store_specific", store_specific=True,
        )
        try:
            result = collect_one(source)
        except Exception as exc:
            low = str(exc).lower()
            kind = "blocked" if "403" in low or "access denied" in low else "timeout" if "timeout" in low else "browser_required"
            raise WebAuditError(kind, str(exc)) from exc
        rows = result.get("offers") or []
        _assert_official_url(store.retailer, result.get("final_url") or source_url)
        self._validate_result(store, result, source_url)
        raw = result.get("raw") or b""
        html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        diagnostics = {
            "html": html, "html_sha256": sha256(html.encode()).hexdigest(),
            "response_bytes": len(html.encode()), "content_type": result.get("content_type"),
            "fetch_mode": result.get("fetch_mode"), "network_payloads": [],
            "console_errors": [], "failed_requests": [], "screenshot_png": None,
        }
        offers = []
        for row in rows:
            offers.append(WebOfferRecord(
                retailer=store.retailer, store_id=store.id, source_url=row.source_url or source_url,
                name=row.product_name, price=row.price, old_price=row.regular_price,
                unit_price=row.unit_price, quantity_value=row.quantity, quantity_unit=row.unit,
                quantity=f"{row.quantity:g} {row.unit}" if row.quantity is not None and row.unit else None,
                packaging_text=f"{row.quantity:g} {row.unit}" if row.quantity is not None and row.unit else None,
                valid_from=_as_date(row.valid_from), valid_to=_as_date(row.valid_to), category=row.category,
                image_url=row.image_url, image_source="retailer_page" if row.image_url else None,
                image_alt=row.image_alt, provenance={"source_text": (row.source_text or "")[:2000], "confidence": row.confidence},
            ))
        offers, duplicates = deduplicate(offers)
        offers = _filter_period(offers, period_key, store.retailer)
        if not offers:
            raise WebAuditError("empty", f"Strukturierter {store.retailer}-Parser lieferte keine sicheren Angebote.", diagnostics)
        return WebAuditResult(
            offers, source_url, result.get("final_url") or source_url,
            self.collector_path, len(rows), duplicates, artifacts=diagnostics,
        )


class ReweWebOfferAdapter(LegacyStructuredAdapter):
    retailer = "REWE"
    collector_path = "rewe_existing_structured_parser"


class NettoWebOfferAdapter(LegacyStructuredAdapter):
    retailer = "Netto Marken-Discount"
    collector_path = "netto_store_page_structured_parser"

    def collect(self, store: Store, source_url: str, period_key: str = "current") -> WebAuditResult:
        if not store.external_id:
            raise WebAuditError("browser_required", "Netto benötigt eine verifizierte storeid und vorausgewählten Filialkontext.")
        return super().collect(store, source_url, period_key)

    def _validate_result(self, store: Store, result: dict, source_url: str) -> None:
        # Netto does not expose the storeid again in the selected-card DOM. It
        # does expose the full selected address. Verify postal code and city so
        # a persistent browser profile can never silently leak another store's
        # offer set into this audit.
        raw = result.get("raw") or b""
        html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        selected = BeautifulSoup(html, "html.parser").select_one(".your-store__box.selected")
        selected_text = _fold(selected.get_text(" ", strip=True) if selected else "")
        if not selected or _fold(store.postal_code) not in selected_text or _fold(store.city) not in selected_text:
            raise WebAuditError(
                "browser_required",
                f"Netto-Browserkontext stimmt nicht mit {store.postal_code} {store.city} überein; fremde Filialdaten werden nicht übernommen.",
                {"html": html, "html_sha256": sha256(html.encode()).hexdigest(), "response_bytes": len(html.encode()), "fetch_mode": result.get("fetch_mode")},
            )


class SemanticHtmlAdapter(RetailerWebOfferAdapter):
    card_selectors: tuple[str, ...] = ("[data-offer-id]", "[id^='i-']", "article")
    use_page_dates = True

    def _name_brand(self, card, image) -> tuple[str, str | None]:
        heading = card.find(["h2", "h3", "h4", "strong", "b"])
        name = _clean((heading or image or {}).get("alt") if not heading and image else heading.get_text(" ", strip=True) if heading else "")
        return re.sub(r"^Angebot\s*:\s*", "", name, flags=re.I), None

    def parse(self, html: str, store: Store, source_url: str, period_key: str) -> list[WebOfferRecord]:
        soup = BeautifulSoup(html, "html.parser")
        page_text = _clean(soup.get_text(" ", strip=True))
        page_dates: list[date] = []
        for match in _DATE.finditer(page_text):
            parsed = _as_date(".".join(match.groups()))
            if parsed and parsed not in page_dates:
                page_dates.append(parsed)
        page_from = min(page_dates) if page_dates else None
        page_to = max(page_dates) if page_dates else None
        cards = []
        for selector in self.card_selectors:
            cards.extend(soup.select(selector))
        offers: list[WebOfferRecord] = []
        seen_nodes: set[int] = set()
        for card in cards:
            if id(card) in seen_nodes:
                continue
            seen_nodes.add(id(card))
            text = _clean(card.get_text(" ", strip=True))
            prices = [value for value in _prices(text) if value > 0]
            image = card.find("img")
            name, brand = self._name_brand(card, image)
            if not name or len(name) > 300:
                continue
            quantity, q_value, q_unit = _quantity(text)
            image_candidates = []
            if image:
                for attribute in ("src", "data-src", "data-lazy-src"):
                    if image.get(attribute):
                        image_candidates.append((urljoin(source_url, image.get(attribute)), _clean(image.get("alt")) or None, 0))
                for srcset in (image.get("srcset"), image.get("data-srcset")):
                    for candidate in (srcset or "").split(","):
                        parts = candidate.strip().split()
                        if not parts:
                            continue
                        score = int(re.sub(r"\D", "", parts[1])) if len(parts) > 1 and re.search(r"\d", parts[1]) else 0
                        image_candidates.append((urljoin(source_url, parts[0]), _clean(image.get("alt")) or None, score))
            image_url, image_alt = _largest_image(image_candidates)
            date_evidence = f"{text} {_clean(image.get('alt')) if image else ''}"
            dates = [_as_date(".".join(match.groups())) for match in _DATE.finditer(date_evidence)]
            dates = [value for value in dates if value]
            range_from, range_to = _date_range(date_evidence)
            offer_link = card.find("a", href=re.compile(r"#?(?:angebot|offer)-", re.I))
            external_offer_id = _clean(card.get("data-offer-id") or card.get("id")) or None
            if not external_offer_id and offer_link:
                external_offer_id = _clean(offer_link.get("href")).lstrip("#") or None
            if not prices and not external_offer_id:
                continue
            offers.append(WebOfferRecord(
                retailer=self.retailer, store_id=store.id, source_url=source_url,
                external_offer_id=external_offer_id,
                name=name, brand=brand, price=prices[-1] if prices else None,
                old_price=prices[-2] if len(prices) > 1 and prices[-2] > prices[-1] else None,
                quantity=quantity, quantity_value=q_value, quantity_unit=q_unit, packaging_text=quantity,
                valid_from=range_from or (dates[0] if dates else page_from if self.use_page_dates else None),
                valid_to=range_to or (dates[1] if len(dates) > 1 else page_to if self.use_page_dates else None),
                image_url=image_url, image_source="retailer_page" if image_url else None,
                image_alt=image_alt,
                provenance={"element": card.name, "classes": card.get("class", []), "text": text[:2000]},
            ))
        return offers


class EdekaWebOfferAdapter(SemanticHtmlAdapter):
    retailer = "EDEKA"
    collector_path = "edeka_market_offer_html"
    card_selectors = ("article",)

    def parse(self, html: str, store: Store, source_url: str, period_key: str) -> list[WebOfferRecord]:
        return _filter_period(super().parse(html, store, source_url, period_key), period_key, self.retailer)


class NormaWebOfferAdapter(SemanticHtmlAdapter):
    retailer = "NORMA"
    collector_path = "norma_week_navigation_html"
    card_selectors = ("article",)
    use_page_dates = False

    def _name_brand(self, card, image) -> tuple[str, str | None]:
        supplier = card.select_one(".supplier")
        headings = [_clean(node.get_text(" ", strip=True)) for node in card.find_all(["h2", "h3", "h4"])]
        if supplier and headings:
            return headings[0], _clean(supplier.get_text(" ", strip=True)) or None
        if len(headings) >= 2:
            return headings[1], headings[0]
        return super()._name_brand(card, image)

    def parse(self, html: str, store: Store, source_url: str, period_key: str) -> list[WebOfferRecord]:
        offers = super().parse(html, store, source_url, period_key)
        match = re.search(r"ab-(?:montag|mittwoch|freitag),-(\d{1,2})\.(\d{1,2})\.(\d{2,4})", source_url, re.I)
        start = _as_date(".".join(match.groups())) if match else None
        for offer in offers:
            if not offer.valid_from:
                offer.valid_from = start
        return offers

    @staticmethod
    def _dated_links(html: str, source_url: str) -> dict[str, date]:
        soup = BeautifulSoup(html, "html.parser")
        links: dict[str, date] = {}
        for anchor in soup.find_all("a", href=True):
            url = urljoin(source_url, anchor.get("href"))
            match = re.search(r"/angebote/ab-(?:montag|mittwoch|freitag),-(\d{1,2})\.(\d{1,2})\.(\d{2,4})", url, re.I)
            if match:
                parsed = _as_date(".".join(match.groups()))
                if parsed:
                    links[url] = parsed
        match = re.search(r"/angebote/ab-(?:montag|mittwoch|freitag),-(\d{1,2})\.(\d{1,2})\.(\d{2,4})", source_url, re.I)
        if match:
            parsed = _as_date(".".join(match.groups()))
            if parsed:
                links[source_url] = parsed
        return links

    def collect(self, store: Store, source_url: str, period_key: str = "current") -> WebAuditResult:
        initial = super().collect(store, source_url, period_key)
        links = self._dated_links(str(initial.artifacts.get("html") or ""), initial.final_url)
        target = app_today() if period_key == "current" else app_today() + timedelta(days=7)
        target_iso = target.isocalendar()[:2]
        selected = [url for url, day in links.items() if day.isocalendar()[:2] == target_iso]
        if period_key == "next" and not selected:
            raise WebAuditError("empty", "NORMA-Navigation enthält noch keinen nächsten Angebotszeitraum.", initial.artifacts)
        results = [initial] if initial.final_url in selected else []
        for url in selected:
            if url == initial.final_url or len(results) >= 7:
                continue
            results.append(super().collect(store, url, period_key))
        if not results:
            raise WebAuditError("empty", f"NORMA-Navigation enthält keine Seiten für ISO-Woche {target_iso[1]}.", initial.artifacts)
        rows = [offer for result in results for offer in result.offers]
        offers, duplicates = deduplicate(rows)
        diagnostics = dict(initial.artifacts)
        diagnostics["selected_period_urls"] = selected
        return WebAuditResult(
            offers=offers, source_url=source_url, final_url=initial.final_url,
            collector_path=self.collector_path, raw_count=sum(result.raw_count for result in results),
            duplicate_count=sum(result.duplicate_count for result in results) + duplicates,
            artifacts=diagnostics,
            message=f"{len(results)} dynamisch aus der Navigation ermittelte Zeitraumseite(n)",
        )


def adapter_for(retailer: str, fetcher=browser_fetch) -> RetailerWebOfferAdapter:
    normalized = _fold(retailer)
    classes = {
        "rewe": ReweWebOfferAdapter,
        "netto marken discount": NettoWebOfferAdapter,
        "netto": NettoWebOfferAdapter,
        "edeka": EdekaWebOfferAdapter,
        "penny": PennyWebOfferAdapter,
        "aldi sud": AldiSuedWebOfferAdapter,
        "norma": NormaWebOfferAdapter,
    }
    cls = classes.get(normalized)
    if not cls:
        raise ValueError(f"Web-Audit unterstützt Händler {retailer!r} nicht")
    return cls(fetcher=fetcher)


def collector_enabled(retailer: str) -> bool:
    return {
        "netto marken discount": settings.web_collector_netto,
        "netto": settings.web_collector_netto,
        "edeka": settings.web_collector_edeka,
        "penny": settings.web_collector_penny,
        "aldi sud": settings.web_collector_aldi_sued,
        "norma": settings.web_collector_norma,
    }.get(_fold(retailer), True)  # REWE remains unchanged.


def _comparison(db: Session, store: Store, offers: list[WebOfferRecord]) -> dict[str, int]:
    web_by_key = {offer.dedupe_key: offer for offer in offers if offer.valid}
    prospect_rows = (
        db.query(Offer, MasterProduct)
        .join(MasterProduct, MasterProduct.id == Offer.master_product_id)
        .filter(Offer.store_id == store.id)
        .all()
    )
    barcodes = {
        product_id: barcode
        for product_id, barcode in db.query(ProductBarcode.master_product_id, ProductBarcode.barcode).all()
    }
    matched_web: set[str] = set()
    price_match = price_mismatch = quantity_match = quantity_mismatch = image_available = 0
    fuzzy_hint_count = 0
    for prospect, product in prospect_rows:
        barcode = barcodes.get(product.id)
        exact = normalize_master_key(" ".join(filter(None, (product.brand, product.name))), *_quantity(product.package_size)[1:])
        family = normalize_master_key(" ".join(filter(None, (product.brand, product.name))))
        match = next((row for row in offers if barcode and row.ean == barcode), None)
        if not match:
            match = next((row for row in offers if normalize_master_key(" ".join(filter(None, (row.brand, row.name))), row.quantity_value, row.quantity_unit) == exact), None)
        if not match:
            family_candidates = [row for row in offers if normalize_master_key(" ".join(filter(None, (row.brand, row.name)))) == family]
            match = family_candidates[0] if len(family_candidates) == 1 else None
        if not match:
            best = max((SequenceMatcher(None, family, normalize_master_key(row.name)).ratio() for row in offers), default=0)
            fuzzy_hint_count += int(best >= 0.82)
            continue
        matched_web.add(match.dedupe_key)
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
    matched = len(matched_web)
    return {
        "prospect_count": len(prospect_rows), "web_count": len(web_by_key), "matched": matched,
        "web_only": max(len(web_by_key) - matched, 0), "prospect_only": max(len(prospect_rows) - matched, 0),
        "price_match": price_match, "price_mismatch": price_mismatch,
        "quantity_match": quantity_match, "quantity_mismatch": quantity_mismatch,
        "image_available": image_available, "fuzzy_hint_count": fuzzy_hint_count,
    }


def _write_artifact(
    run: WebOfferAuditRun,
    result: WebAuditResult | None,
    error: Exception | None = None,
    diagnostics: dict | None = None,
) -> str:
    root = settings.data_dir / "diagnostics" / "web_offer_audit" / str(run.store_id)
    root.mkdir(parents=True, exist_ok=True)
    prefix = f"run-{run.id}-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    path = root / f"{prefix}.json"
    evidence = diagnostics or (result.artifacts if result else {})
    network_payloads = evidence.get("network_payloads") if isinstance(evidence.get("network_payloads"), list) else []
    payload = {
        "run_id": run.id, "store_id": run.store_id, "retailer": run.retailer,
        "source_url": run.source_url, "status": run.status, "error_type": run.error_type,
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
            "offers": [{**asdict(row), "valid_from": str(row.valid_from) if row.valid_from else None,
                        "valid_to": str(row.valid_to) if row.valid_to else None,
                        "collected_at": row.collected_at.isoformat()} for row in result.offers[:1000]],
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
            (root / f"{prefix}.network.json").write_text(
                json.dumps(bounded, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
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
        store_id=store.id, retailer=store.retailer, period_key=period_key,
        source_url=url, collector_path=adapter.collector_path, status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    started = time.monotonic()
    result = None
    failure = None
    try:
        result = adapter.collect(store, url, period_key)
        run.final_url = result.final_url
        run.raw_count = result.raw_count
        run.duplicate_count = result.duplicate_count
        run.valid_count = sum(row.valid for row in result.offers)
        run.missing_price_count = sum(row.price is None for row in result.offers)
        run.missing_image_count = sum(not row.image_url for row in result.offers)
        run.missing_package_count = sum(not row.packaging_text for row in result.offers)
        comparison = _comparison(db, store, result.offers)
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
