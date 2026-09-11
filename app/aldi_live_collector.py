from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from .collection_quality import BenchmarkContext
from .collection_service import CollectionError, collect_structured_for_store
from .engine_v140.collectors import best_img, fetch_source, images, parse_aldi_text, visible
from .engine_v140.price_units import compute_unit_price
from .models import Store


_ALLOWED_HOSTS = {"aldi-sued.de", "www.aldi-sued.de"}
_ALLOWED_PATHS = {"/angebote", "/angebote/", "/tools/features/angebote", "/tools/features/angebote/"}
_FILIAL_SELECTOR_RE = re.compile(
    r"(?:wähle\s+deine\s+filiale|filialauswahl|filiale\s+auswählen)",
    re.IGNORECASE,
)
_SAVING_PRICE_RE = re.compile(
    r"\bSpare\s+\d{1,2}\s*%\s*(\d{1,3}[.,]\d{2})\s*€(?:\s*[²*]?\s*)(\d{1,3}[.,]\d{2})\s*€",
    re.IGNORECASE,
)
_DEPOSIT_RE = re.compile(
    r"(?:(\d{1,3}[.,]\d{2})\s*€\s*\+?\s*(?:Pfand|Mehrweg|Einweg)|(?:Pfand|Mehrweg|Einweg)\s*(\d{1,3}[.,]\d{2})\s*€)",
    re.IGNORECASE,
)
_SIZE_TOKEN_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stück|stk\.?)\b",
    re.IGNORECASE,
)
_UNIT_PRICE_PAREN_RE = re.compile(r"\([^)]*(?:€\s*/|/\s*1?\s*(?:kg|l)|(?:kg|l)\s*=)[^)]*\)", re.I)


def is_official_aldi_offer_url(url: str) -> bool:
    """Return True only for ALDI SÜD's canonical stationary offer pages."""
    parsed = urlparse((url or "").strip())
    return parsed.scheme == "https" and parsed.hostname in _ALLOWED_HOSTS and parsed.path in _ALLOWED_PATHS


def _has_explicit_week_window(offer) -> bool:
    return bool(getattr(offer, "valid_from", None) and getattr(offer, "valid_to", None))


def _deposit_values(text: str) -> set[float]:
    values: set[float] = set()
    for match in _DEPOSIT_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2)
        if raw:
            values.add(float(raw.replace(",", ".")))
    return values


def _more_specific_name(row) -> str | None:
    """Recover a concrete package-bearing title from an over-broad ALDI label.

    The live ALDI DOM can expose section/category text directly before the
    actual product title. The legacy line parser can then emit both the broad
    label (for example ``Kühlung BBQ``) and the real package-bearing product.
    Only replace a broad current name when the source block starts with it and
    immediately contains a clearly more specific title with its own pack size.
    """
    current = str(getattr(row, "product_name", "") or "").strip()
    block = str(getattr(row, "source_text", "") or "").strip()
    if not current or not block or _SIZE_TOKEN_RE.search(current):
        return None
    prefix = re.split(r"\bSpare\s+\d{1,2}\s*%", block, maxsplit=1, flags=re.I)[0].strip()
    if not prefix.lower().startswith(current.lower()):
        return None
    remainder = prefix[len(current) :].strip(" ·|:-")
    if not remainder:
        return None
    remainder = _UNIT_PRICE_PAREN_RE.sub(" ", remainder)
    match = re.match(
        r"(.{3,120}?\b\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stück|stk\.?)\b)",
        remainder,
        re.IGNORECASE,
    )
    if not match:
        return None
    candidate = " ".join(match.group(1).split()).strip(" ·|:-")
    return candidate if len(candidate) >= 4 else None


def _harden_aldi_row(row, imgs):
    """Correct known live ALDI card ambiguities without inventing offer data."""
    block = str(getattr(row, "source_text", "") or "")
    updated = row

    better_name = _more_specific_name(updated)
    if better_name:
        updated = replace(updated, product_name=better_name, category=getattr(updated, "category", "Sonstiges"))

    deposits = _deposit_values(block)
    original_price = getattr(row, "price", None)

    # Prefer the explicit ALDI saving pair over arbitrary minimum-price logic.
    # If the legacy parser actually selected a Pfand value, the block has
    # already crossed a card boundary; fail closed rather than borrowing the
    # following product's saving pair.
    saving = _SAVING_PRICE_RE.search(block)
    if saving:
        if original_price in deposits:
            return None
        promo = float(saving.group(1).replace(",", "."))
        regular = float(saving.group(2).replace(",", "."))
        if regular <= promo:
            regular = None
        updated = replace(updated, price=promo, regular_price=regular)
    elif original_price in deposits:
        return None

    if not getattr(updated, "image_url", None):
        image = best_img(imgs or [], getattr(updated, "product_name", ""))
        if image:
            updated = replace(updated, image_url=image["url"], image_alt=image["alt"])

    if getattr(updated, "price", None) is not None and getattr(updated, "quantity", None) is not None:
        unit_price, unit_price_unit = compute_unit_price(
            updated.price,
            updated.quantity,
            getattr(updated, "unit", None),
        )
        if unit_price is not None:
            # Unit prices are consumer-facing monetary values. Keep the shared
            # helper's internal precision, but persist ALDI output at cent
            # precision so 3.99 / 0.4 kg becomes 9.98 €/kg, not 9.975.
            updated = replace(updated, unit_price=round(unit_price, 2), unit_price_unit=unit_price_unit)
    return updated


def parse_aldi_stationary_chain_offers(source, text: str, imgs=None):
    """Parse only explicitly dated weekly ALDI SÜD in-store offers.

    The public ALDI offer page is a regional-chain source. Its generic filial
    selector is an availability helper, not evidence that the advertised price
    belongs to a different branch. The legacy parser treated that selector as a
    hard stop unless the concrete city occurred in the page text. For the
    canonical ALDI offer URL we remove only those selector labels, then retain
    only rows carrying an explicit start *and* end date from a weekly heading.

    Product-level stock availability is deliberately not promoted to branch
    availability here; that remains an independent QA concern.
    """
    if source.retailer != "ALDI SÜD":
        raise CollectionError(f"Kein ALDI-SÜD-Collector: {source.store_name}")
    if not is_official_aldi_offer_url(source.url):
        raise CollectionError(f"Nicht freigegebene ALDI-SÜD-Quelle: {source.url}")

    parser_text = _FILIAL_SELECTOR_RE.sub("", text or "")
    image_rows = imgs or []
    rows = parse_aldi_text(source, parser_text, image_rows)

    result = []
    seen = set()
    for row in rows:
        if not _has_explicit_week_window(row):
            continue
        hardened = _harden_aldi_row(row, image_rows)
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
        if key in seen:
            continue
        seen.add(key)
        result.append(hardened)
    return result


def collect_aldi_web_for_store(
    db: Session,
    store: Store,
    *,
    benchmark_context: BenchmarkContext | str = BenchmarkContext.NOT_APPLICABLE,
):
    """Collect chain-advertised stationary ALDI SÜD offers for one target store.

    Dierdorf and Oberhonnefeld-Gierend intentionally share the official ALDI
    SÜD offer source. Import remains store-scoped, while the source provenance
    is recorded as ``regional_chain``. No PDF fallback is used here: an
    ambiguous/undated prospect must fail safely instead of becoming local data.
    """
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
                "Offizielle ALDI-SÜD-Angebotsseite; beworbene Wochenangebote "
                "werden als stationäre Regional-Chain-Angebote behandelt. "
                "Filialbestand bleibt unabhängige QA."
            ),
        )
        fetched = fetch_source(resolved)
        raw, content_type, fetch_mode, final_url = fetched
        html = raw.decode("utf-8", errors="replace")
        text = visible(html)
        image_rows = images(html, final_url or resolved.url)
        offers = parse_aldi_stationary_chain_offers(resolved, text, image_rows)
        if not offers:
            raise CollectionError(
                "ALDI SÜD lieferte keine sicher datierten stationären Wochenangebote"
            )
        return {
            "source": resolved,
            "raw": raw,
            "content_type": content_type,
            "fetch_mode": fetch_mode,
            "final_url": final_url,
            "offers": offers,
            "status": "parsed",
            "aldi_scope": "regional_chain_stationary",
            "technical_warning": "",
        }

    result, summary, run = collect_structured_for_store(
        db,
        store.name,
        collector_fn=collector,
        benchmark_context=benchmark_context,
    )
    return result, summary, run
