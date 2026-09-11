from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from .collection_quality import BenchmarkContext
from .collection_service import CollectionError, collect_structured_for_store
from .engine_v140.collectors import fetch_source, images, parse_aldi_text, visible
from .models import Store


_ALLOWED_HOSTS = {"aldi-sued.de", "www.aldi-sued.de"}
_ALLOWED_PATHS = {"/angebote", "/angebote/", "/tools/features/angebote", "/tools/features/angebote/"}
_FILIAL_SELECTOR_RE = re.compile(
    r"(?:wähle\s+deine\s+filiale|filialauswahl|filiale\s+auswählen)",
    re.IGNORECASE,
)


def is_official_aldi_offer_url(url: str) -> bool:
    """Return True only for ALDI SÜD's canonical stationary offer pages."""
    parsed = urlparse((url or "").strip())
    return parsed.scheme == "https" and parsed.hostname in _ALLOWED_HOSTS and parsed.path in _ALLOWED_PATHS


def _has_explicit_week_window(offer) -> bool:
    return bool(getattr(offer, "valid_from", None) and getattr(offer, "valid_to", None))


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
    rows = parse_aldi_text(source, parser_text, imgs or [])
    return [row for row in rows if _has_explicit_week_window(row)]


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
