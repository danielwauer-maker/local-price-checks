from __future__ import annotations

from datetime import date
from hashlib import sha256
import re
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from .config import settings
from .models import Store
from .web_offer_audit import WebAuditError, WebAuditResult, WebOfferRecord, _clean, _quantity
from .web_offer_audit_runtime import quality_deduplicate

FELLENZER_MARKET_ID = "071378"
FELLENZER_OFFERS_URL = "https://edeka-fellenzer.de/angebote/"
_ALLOWED_HOSTS = {"edeka-fellenzer.de", "www.edeka-fellenzer.de"}
_IMAGE_HOST = "media.smp-it-media.de"
_PRICE_RE = re.compile(r"(?<!\d)(\d{1,3})\s*[.,]\s*(\d{2})(?!\d)")
_VALIDITY_RE = re.compile(
    r"gültig\s+vom\s+(\d{1,2})\.(\d{1,2})\.\s*(?:bis\s+(?:zum\s+)?)?(\d{1,2})\.(\d{1,2})\.(\d{4})",
    re.I,
)
_SKIP_ALT_RE = re.compile(r"(?:logo|prospekt|pdf|download|banner|header|footer)", re.I)


def _trusted_fellenzer_image(url: str | None) -> bool:
    if not url or url.startswith("data:"):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and host == _IMAGE_HOST and bool(parsed.path)


class FellenzerWebOfferRecord(WebOfferRecord):
    """Keep verified Fellenzer CDN images even when their URL has no suffix.

    The shared validator intentionally requires a known image CDN or a classic
    image filename extension. Fellenzer's official CDN serves product images as
    `/products/image/<opaque-id>` without `.jpg`/`.png`, so the generic rule
    rejects otherwise valid images. This subclass restores only HTTPS images on
    the exact verified Fellenzer image host; all other validation remains shared.
    """

    def validate(self) -> "FellenzerWebOfferRecord":
        original_image = self.image_url
        original_source = self.image_source
        super().validate()
        if _trusted_fellenzer_image(original_image):
            self.image_url = original_image
            self.image_source = original_source
            self.validation_errors = [error for error in self.validation_errors if error != "invalid_image"]
        return self


def _price(text: str) -> float | None:
    match = _PRICE_RE.search(text or "")
    if not match:
        return None
    return float(f"{match.group(1)}.{match.group(2)}")


def _validity(text: str) -> tuple[date | None, date | None]:
    match = _VALIDITY_RE.search(text or "")
    if not match:
        return None, None
    year = int(match.group(5))
    try:
        return (
            date(year, int(match.group(2)), int(match.group(1))),
            date(year, int(match.group(4)), int(match.group(3))),
        )
    except ValueError:
        return None, None


def _image_url(img, base_url: str) -> str | None:
    for attribute in ("data-src", "data-lazy-src", "src"):
        value = _clean(img.get(attribute))
        if value and not value.startswith("data:"):
            return urljoin(base_url, value)
    srcset = _clean(img.get("srcset") or img.get("data-srcset"))
    if srcset:
        candidate = srcset.split(",")[-1].strip().split(" ")[0]
        if candidate:
            return urljoin(base_url, candidate)
    return None


def _offer_container(img, title: str):
    node = img.parent
    for _ in range(8):
        if node is None:
            return None
        text = _clean(" ".join(node.stripped_strings))
        if title.lower() in text.lower() and _PRICE_RE.search(text) and len(text) <= 1800:
            return node
        node = node.parent
    return None


def _description(container, title: str) -> str | None:
    strings = [_clean(value) for value in container.stripped_strings]
    strings = [value for value in strings if value]
    title_index = next((index for index, value in enumerate(strings) if title.lower() in value.lower()), -1)
    if title_index < 0:
        return None
    parts: list[str] = []
    for value in strings[title_index + 1 :]:
        if value == title or _PRICE_RE.fullmatch(value.replace("€", "").strip()):
            continue
        if value.lower() in {"mehr laden", "weniger laden"}:
            break
        parts.append(value)
    text = _clean(" ".join(parts))
    return text[:1200] or None


def _parse_html(html: str, store: Store, source_url: str = FELLENZER_OFFERS_URL) -> WebAuditResult:
    started = time.monotonic()
    soup = BeautifulSoup(html, "html.parser")
    page_text = _clean(" ".join(soup.stripped_strings))
    valid_from, valid_to = _validity(page_text)

    candidates = 0
    raw: list[WebOfferRecord] = []
    seen_images: set[tuple[str, str]] = set()
    for img in soup.find_all("img"):
        title = _clean(img.get("alt"))
        image_url = _image_url(img, source_url)
        if not title or _SKIP_ALT_RE.search(title) or not image_url:
            continue
        if not _trusted_fellenzer_image(image_url):
            continue
        key = (title.lower(), image_url)
        if key in seen_images:
            continue
        seen_images.add(key)
        candidates += 1

        container = _offer_container(img, title)
        if container is None:
            continue
        text = _clean(" ".join(container.stripped_strings))
        price = _price(text)
        if price is None:
            continue
        description = _description(container, title)
        quantity, quantity_value, quantity_unit = _quantity(" ".join(part for part in (title, description or "") if part))
        fingerprint = sha256(f"{title}|{price:.2f}|{description or ''}".encode("utf-8")).hexdigest()[:24]
        raw.append(
            FellenzerWebOfferRecord(
                retailer="EDEKA",
                store_id=store.id,
                source_url=source_url,
                external_offer_id=f"fellenzer:{fingerprint}",
                name=title,
                description=description,
                price=price,
                quantity=quantity,
                quantity_value=quantity_value,
                quantity_unit=quantity_unit,
                packaging_text=quantity or description,
                valid_from=valid_from,
                valid_to=valid_to,
                image_url=image_url,
                image_source="edeka_fellenzer_official",
                image_alt=title,
                provenance={
                    "source": "official_store_site",
                    "host": "edeka-fellenzer.de",
                    "market_id": FELLENZER_MARKET_ID,
                },
            ).validate()
        )

    offers, duplicates = quality_deduplicate(raw)
    if not offers:
        raise WebAuditError(
            "empty",
            "Offizielle EDEKA-Fellenzer-Seite lieferte keine parsebaren Angebote.",
            {"source_url": source_url, "candidate_images": candidates},
        )
    if candidates >= 10 and len(raw) < max(5, int(candidates * 0.70)):
        raise WebAuditError(
            "endpoint_changed",
            "EDEKA-Fellenzer-Seite enthält deutlich mehr Produktbilder als parsebare Angebotskarten; HTML-Struktur hat sich möglicherweise geändert.",
            {"source_url": source_url, "candidate_images": candidates, "parsed": len(raw)},
        )

    diagnostics = {
        "fetch_mode": "edeka-fellenzer-official-html",
        "source_url": source_url,
        "candidate_images": candidates,
        "parsed_count": len(raw),
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
        "network_payloads": [],
        "console_errors": [],
        "failed_requests": [],
    }
    return WebAuditResult(
        offers=offers,
        source_url=source_url,
        final_url=source_url,
        collector_path="edeka_fellenzer_official_html",
        raw_count=len(raw),
        duplicate_count=duplicates,
        message=f"{round((time.monotonic() - started) * 1000)} ms via offizielle EDEKA-Fellenzer-Seite",
        artifacts=diagnostics,
    )


def fetch_fellenzer_offers(store: Store, http_get=httpx.get) -> WebAuditResult:
    market_id = "".join(character for character in str(store.external_id or "") if character.isdigit())
    if market_id != FELLENZER_MARKET_ID:
        raise WebAuditError("blocked", "Fellenzer-Collector ist ausschließlich für den verifizierten Markt 071378 freigegeben.")
    try:
        response = http_get(
            FELLENZER_OFFERS_URL,
            follow_redirects=True,
            timeout=settings.collector_timeout_seconds,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "de-DE,de;q=0.9",
                "User-Agent": "Spareno-Web-Audit/1.0",
            },
        )
    except httpx.TimeoutException as exc:
        raise WebAuditError("timeout", f"EDEKA-Fellenzer-Seite Timeout: {exc}") from exc
    except httpx.HTTPError as exc:
        raise WebAuditError("endpoint_changed", f"EDEKA-Fellenzer-Seite HTTP-Fehler: {exc}") from exc

    final_host = (urlparse(str(response.url)).hostname or "").lower().rstrip(".")
    if final_host not in _ALLOWED_HOSTS:
        raise WebAuditError("blocked", f"Unerwartetes Redirect-Ziel der Fellenzer-Seite: {final_host or 'ohne Host'}")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise WebAuditError("endpoint_changed", f"EDEKA-Fellenzer-Seite antwortet mit HTTP {response.status_code}.") from exc
    return _parse_html(response.text, store, str(response.url))
