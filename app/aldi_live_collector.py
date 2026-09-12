from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .aldi_structured_extractor import parse_aldi_offer_cards
from .collection_quality import BenchmarkContext
from .collection_service import CollectionError, collect_structured_for_store
from .engine_v140.collectors import best_img, fetch_source, images, parse_aldi_text, visible
from .engine_v140.price_units import compute_unit_price
from .models import MasterProduct, Offer, OfferOccurrence, OfferPriceReference, Store


_ALLOWED_HOSTS = {"aldi-sued.de", "www.aldi-sued.de"}
_ALLOWED_PATHS = {"/angebote", "/angebote/", "/tools/features/angebote", "/tools/features/angebote/"}
_WEEKLY_CATEGORY_PATHS = {
    "/produkte/wochenangebote/frischeprodukte-im-angebot/k/1588161427299187",
    "/produkte/wochenangebote/eigenmarken-im-angebot/k/1588161427299188",
    "/produkte/wochenangebote/markenprodukte-im-angebot/k/1588161427299189",
}
_WEEKLY_CATEGORY_URLS = tuple(f"https://www.aldi-sued.de{path}" for path in sorted(_WEEKLY_CATEGORY_PATHS))
_FILIAL_SELECTOR_RE = re.compile(
    r"(?:wähle\s+deine\s+filiale|filialauswahl|filiale\s+auswählen)", re.IGNORECASE
)
_SAVING_PRICE_RE = re.compile(
    r"\bSpare\s+\d{1,2}\s*%\s*(\d{1,3}[.,]\d{2})\s*€(?:\s*[²*]?\s*)(\d{1,3}[.,]\d{2})\s*€",
    re.IGNORECASE,
)
_DEPOSIT_RE = re.compile(
    r"(?:(\d{1,3}[.,]\d{2})\s*€\s*\+?\s*(?:Pfand|Mehrweg|Einweg)|(?:Pfand|Mehrweg|Einweg)\s*(\d{1,3}[.,]\d{2})\s*€)",
    re.IGNORECASE,
)
_SIZE_TOKEN_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stück|stk\.?)\b", re.I)
_UNIT_PRICE_PAREN_RE = re.compile(r"\([^)]*(?:€\s*/|/\s*1?\s*(?:kg|l)|(?:kg|l)\s*=)[^)]*\)", re.I)


def is_official_aldi_offer_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    return parsed.scheme == "https" and parsed.hostname in _ALLOWED_HOSTS and parsed.path in _ALLOWED_PATHS


def is_official_aldi_weekly_url(url: str) -> bool:
    """Allow only the three official weekly category pages and their pagination."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        return False
    if parsed.path not in _WEEKLY_CATEGORY_PATHS:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not query:
        return True
    if set(query) != {"page"} or len(query["page"]) != 1:
        return False
    value = query["page"][0]
    return value.isdigit() and 1 <= int(value) <= 10


def _has_explicit_week_window(offer) -> bool:
    return bool(getattr(offer, "valid_from", None) and getattr(offer, "valid_to", None))


def _deposit_values(text: str) -> set[float]:
    values: set[float] = set()
    for match in _DEPOSIT_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2)
        if raw:
            values.add(float(raw.replace(",", ".")))
    return values


def _money_round(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _more_specific_name(row) -> str | None:
    current = str(getattr(row, "product_name", "") or "").strip()
    block = str(getattr(row, "source_text", "") or "").strip()
    if not current or not block or _SIZE_TOKEN_RE.search(current):
        return None
    prefix = re.split(r"\bSpare\s+\d{1,2}\s*%", block, maxsplit=1, flags=re.I)[0].strip()
    if not prefix.lower().startswith(current.lower()):
        return None
    remainder = _UNIT_PRICE_PAREN_RE.sub(" ", prefix[len(current) :].strip(" ·|:-"))
    match = re.match(r"(.{3,120}?\b\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stück|stk\.?)\b)", remainder, re.I)
    if not match:
        return None
    candidate = " ".join(match.group(1).split()).strip(" ·|:-")
    return candidate if len(candidate) >= 4 else None


def _harden_aldi_row(row, imgs):
    """Compatibility hardening for legacy text-only fixtures."""
    block = str(getattr(row, "source_text", "") or "")
    updated = row
    better_name = _more_specific_name(updated)
    if better_name:
        updated = replace(updated, product_name=better_name, category=getattr(updated, "category", "Sonstiges"))

    deposits = _deposit_values(block)
    original_price = getattr(row, "price", None)
    saving = _SAVING_PRICE_RE.search(block)
    if saving:
        if original_price in deposits:
            return None
        promo = float(saving.group(1).replace(",", "."))
        regular = float(saving.group(2).replace(",", "."))
        updated = replace(updated, price=promo, regular_price=regular if regular > promo else None)
    elif original_price in deposits:
        return None

    if not getattr(updated, "image_url", None):
        image = best_img(imgs or [], getattr(updated, "product_name", ""))
        if image:
            updated = replace(updated, image_url=image["url"], image_alt=image["alt"])

    if getattr(updated, "price", None) is not None and getattr(updated, "quantity", None) is not None:
        unit_price, unit_price_unit = compute_unit_price(updated.price, updated.quantity, getattr(updated, "unit", None))
        if unit_price is not None:
            updated = replace(updated, unit_price=_money_round(unit_price), unit_price_unit=unit_price_unit)
    return updated


def parse_aldi_stationary_chain_offers(source, text: str, imgs=None):
    """Legacy text-only parser retained for compatibility and unit fixtures."""
    if source.retailer != "ALDI SÜD":
        raise CollectionError(f"Kein ALDI-SÜD-Collector: {source.store_name}")
    if not is_official_aldi_offer_url(source.url):
        raise CollectionError(f"Nicht freigegebene ALDI-SÜD-Quelle: {source.url}")

    rows = parse_aldi_text(source, _FILIAL_SELECTOR_RE.sub("", text or ""), imgs or [])
    result = []
    seen = set()
    for row in rows:
        if not _has_explicit_week_window(row):
            continue
        hardened = _harden_aldi_row(row, imgs or [])
        if hardened is None:
            continue
        key = (
            str(getattr(hardened, "product_name", "") or "").lower(),
            getattr(hardened, "price", None),
            getattr(hardened, "quantity", None),
            getattr(hardened, "unit", None),
            getattr(hardened, "valid_from", None),
            getattr(hardened, "valid_to", None),
        )
        if key not in seen:
            seen.add(key)
            result.append(hardened)
    return result


def parse_aldi_stationary_chain_document(
    source,
    html: str,
    text: str,
    imgs=None,
    *,
    allow_single_price: bool = False,
):
    """Primary production parser: one isolated DOM card becomes one offer."""
    if source.retailer != "ALDI SÜD":
        raise CollectionError(f"Kein ALDI-SÜD-Collector: {source.store_name}")
    if not (is_official_aldi_offer_url(source.url) or is_official_aldi_weekly_url(source.url)):
        raise CollectionError(f"Nicht freigegebene ALDI-SÜD-Quelle: {source.url}")
    return parse_aldi_offer_cards(
        source,
        html,
        _FILIAL_SELECTOR_RE.sub("", text or ""),
        imgs or [],
        allow_single_price=allow_single_price,
    )


def _discover_weekly_page_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    urls = []
    for anchor in soup.find_all("a", href=True):
        candidate = urljoin(base_url, str(anchor.get("href") or ""))
        if candidate == base_url or not is_official_aldi_weekly_url(candidate):
            continue
        if urlparse(candidate).path != urlparse(base_url).path:
            continue
        if candidate not in urls:
            urls.append(candidate)
    return urls[:9]


def _offer_key(row):
    return (
        " ".join(str(getattr(row, "product_name", "") or "").lower().split()),
        round(float(getattr(row, "price", 0.0) or 0.0), 2),
        getattr(row, "quantity", None),
        getattr(row, "unit", None),
        getattr(row, "valid_from", None),
        getattr(row, "valid_to", None),
    )


def _parse_day(value):
    return datetime.strptime(str(value), "%d.%m.%Y").date()


def _select_current_aldi_week_offers(rows, *, today: date | None = None):
    """Keep exactly one offer window that is active today; ignore stale/future ALDI cards."""
    candidates = list(rows or [])
    current_day = today or date.today()
    active_by_window: dict[tuple[str, str], list] = {}
    available_windows: set[tuple[str, str]] = set()

    for row in candidates:
        if not _has_explicit_week_window(row):
            continue
        valid_from_raw = str(row.valid_from)
        valid_to_raw = str(row.valid_to)
        try:
            valid_from = _parse_day(valid_from_raw)
            valid_to = _parse_day(valid_to_raw)
        except (TypeError, ValueError) as exc:
            raise CollectionError(
                f"ALDI SÜD lieferte ein ungültiges Angebotsdatum: {valid_from_raw}–{valid_to_raw}"
            ) from exc
        if valid_to < valid_from:
            raise CollectionError(
                f"ALDI SÜD lieferte ein ungültiges Angebotsfenster: {valid_from_raw}–{valid_to_raw}"
            )

        window = (valid_from_raw, valid_to_raw)
        available_windows.add(window)
        if valid_from <= current_day <= valid_to:
            active_by_window.setdefault(window, []).append(row)

    if len(active_by_window) != 1:
        if not active_by_window:
            raise CollectionError(
                "ALDI SÜD lieferte keine eindeutig aktuell gültige Angebotswoche; "
                f"gefundene Fenster: {sorted(available_windows)}"
            )
        raise CollectionError(
            "ALDI SÜD lieferte mehrere aktuell gültige Angebotswochen: "
            f"{sorted(active_by_window)}"
        )

    active_window, active_rows = next(iter(active_by_window.items()))
    return active_rows, active_window, available_windows


def _prune_stale_aldi_week_offers(db: Session, store: Store, safe_rows) -> int:
    """Remove old current-week ALDI rows not reproduced by the safe parser."""
    rows = list(safe_rows or [])
    if len(rows) < 20:
        return 0
    windows = {(getattr(r, "valid_from", None), getattr(r, "valid_to", None)) for r in rows}
    if len(windows) != 1:
        return 0
    valid_from_raw, valid_to_raw = next(iter(windows))
    if not valid_from_raw or not valid_to_raw:
        return 0
    valid_from, valid_to = _parse_day(valid_from_raw), _parse_day(valid_to_raw)
    safe_keys = {
        (" ".join(str(r.product_name).lower().split()), round(float(r.price), 2))
        for r in rows
        if getattr(r, "product_name", None) and getattr(r, "price", None) is not None
    }

    candidates = (
        db.query(Offer)
        .join(MasterProduct, Offer.master_product_id == MasterProduct.id)
        .filter(Offer.store_id == store.id, Offer.valid_from == valid_from, Offer.valid_to == valid_to)
        .all()
    )
    stale = []
    for offer in candidates:
        source_url = offer.source_url or ""
        if not (is_official_aldi_offer_url(source_url) or is_official_aldi_weekly_url(source_url)):
            continue
        key = (" ".join(str(offer.product.name).lower().split()), round(float(offer.price), 2))
        if key not in safe_keys:
            stale.append(offer)

    for offer in stale:
        db.query(OfferOccurrence).filter(OfferOccurrence.offer_id == offer.id).delete(synchronize_session=False)
        db.query(OfferPriceReference).filter(OfferPriceReference.offer_id == offer.id).delete(synchronize_session=False)
        db.delete(offer)
    if stale:
        db.commit()
    return len(stale)


def collect_aldi_web_for_store(
    db: Session,
    store: Store,
    *,
    benchmark_context: BenchmarkContext | str = BenchmarkContext.NOT_APPLICABLE,
):
    if store.retailer != "ALDI SÜD":
        raise CollectionError(f"Kein ALDI-SÜD-Markt: {store.name}")

    def collector(source):
        if not is_official_aldi_offer_url(source.url):
            raise CollectionError(f"Nicht freigegebene ALDI-SÜD-Quelle: {source.url}")
        resolved = replace(
            source,
            locality="regional_chain",
            store_specific=False,
            notes=(
                "Offizielle ALDI-SÜD-Wochenangebotsseiten; strukturierte DOM-Karten. "
                "Filialbestand bleibt unabhängige QA."
            ),
        )

        raw, content_type, fetch_mode, final_url = fetch_source(resolved)
        html = raw.decode("utf-8", errors="replace")
        text = visible(html)
        image_rows = images(html, final_url or resolved.url)
        all_offers = parse_aldi_stationary_chain_document(resolved, html, text, image_rows)
        fetched_pages = [final_url or resolved.url]

        for root_url in _WEEKLY_CATEGORY_URLS:
            category_source = replace(resolved, url=root_url)
            category_raw, _, _, category_final = fetch_source(category_source)
            category_html = category_raw.decode("utf-8", errors="replace")
            category_text = visible(category_html)
            category_images = images(category_html, category_final or root_url)
            category_source = replace(category_source, url=category_final or root_url)
            category_offers = parse_aldi_stationary_chain_document(
                category_source,
                category_html,
                category_text,
                category_images,
                allow_single_price=True,
            )
            if not category_offers:
                raise CollectionError(f"ALDI SÜD Wochenkategorie ohne sichere Angebote: {root_url}")
            all_offers.extend(category_offers)
            fetched_pages.append(category_source.url)

            for page_url in _discover_weekly_page_urls(category_html, category_source.url):
                page_source = replace(resolved, url=page_url)
                page_raw, _, _, page_final = fetch_source(page_source)
                page_html = page_raw.decode("utf-8", errors="replace")
                page_text = visible(page_html)
                page_images = images(page_html, page_final or page_url)
                page_source = replace(page_source, url=page_final or page_url)
                page_offers = parse_aldi_stationary_chain_document(
                    page_source,
                    page_html,
                    page_text,
                    page_images,
                    allow_single_price=True,
                )
                all_offers.extend(page_offers)
                fetched_pages.append(page_source.url)

        deduped = []
        seen = set()
        for row in all_offers:
            key = _offer_key(row)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)

        if not deduped:
            raise CollectionError("ALDI SÜD lieferte keine sicher isolierten, datierten Angebotskarten")

        current_offers, active_window, available_windows = _select_current_aldi_week_offers(deduped)

        return {
            "source": resolved,
            "raw": raw,
            "content_type": content_type,
            "fetch_mode": fetch_mode,
            "final_url": final_url,
            "offers": current_offers,
            "status": "parsed",
            "aldi_scope": "regional_chain_stationary",
            "parser_mode": "structured_weekly_categories_v3",
            "weekly_pages_fetched": len(dict.fromkeys(fetched_pages)),
            "active_week": active_window,
            "available_week_windows": sorted(available_windows),
            "noncurrent_offers_discarded": len(deduped) - len(current_offers),
            "technical_warning": "",
        }

    result, summary, run = collect_structured_for_store(
        db,
        store.name,
        collector_fn=collector,
        benchmark_context=benchmark_context,
    )
    if getattr(run, "status", None) == "success" and isinstance(result, dict):
        pruned = _prune_stale_aldi_week_offers(db, store, result.get("offers") or [])
        result["stale_aldi_offers_pruned"] = pruned
    return result, summary, run
