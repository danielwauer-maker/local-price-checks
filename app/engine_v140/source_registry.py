from dataclasses import dataclass
import re


@dataclass(frozen=True)
class RetailSource:
    key: str
    retailer: str
    store_name: str
    url: str
    mode: str
    locality: str
    notes: str = ""
    supports_products: bool = True
    store_specific: bool = False
    alternate_urls: tuple[str, ...] = ()


EDEKA_MARKET_PATH_RE = re.compile(r"^(https://www\.edeka\.de/maerkte/\d{6}/)(?:angebote/|prospekte/)?$", re.I)
REWE_MARKET_PAGE_RE = re.compile(
    r"^https://www\.rewe\.de/marktseite/([^/?#]+)/(\d+)/([^/?#]+)/?(?:[?#].*)?$",
    re.I,
)


def _normalize_edeka_market_url(url: str) -> str:
    """Prefer the canonical market root for EDEKA prospect discovery.

    The market root exposes the prospect/catalog entry while the dedicated
    ``/angebote/`` route can return Akamai 403 to server-side collectors.
    Normalize known market-specific URLs generically so newly onboarded EDEKA
    stores do not depend on the blocked sub-route.
    """
    match = EDEKA_MARKET_PATH_RE.match((url or "").strip())
    return match.group(1) if match else (url or "").strip()


def _normalize_rewe_collection_url(url: str) -> str:
    """Use REWE's market-specific offer route for collection.

    Store onboarding deliberately keeps the official ``/marktseite/`` URL as
    identity evidence. The offer collector, however, is benchmarked against
    REWE's ``/angebote/<city>/<market-id>/<slug>/`` route (for example the
    Hundertmark market in Dierdorf). Convert only canonical REWE market-page
    URLs; already-canonical offer URLs and unrelated URLs pass through.
    """
    raw = (url or "").strip()
    match = REWE_MARKET_PAGE_RE.match(raw)
    if not match:
        return raw
    city_slug, market_id, market_slug = match.groups()
    return f"https://www.rewe.de/angebote/{city_slug}/{market_id}/{market_slug}/"


SOURCES = [
    RetailSource(
        "rewe_dierdorf", "REWE", "REWE:XL Hundertmark",
        "https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
        "store_page", "store_specific", "Marktbezogene offizielle REWE-Angebotsseite.", True, True,
    ),
    RetailSource(
        "rewe_strassenhaus", "REWE", "REWE Dennis Weirich",
        "https://www.rewe.de/angebote/strassenhaus/1940425/rewe-markt-kirschbuechel-2/",
        "store_page", "store_specific", "Marktbezogene offizielle REWE-Angebotsseite; Vollbenchmark noch offen.", True, True,
    ),
    RetailSource(
        "netto_dierdorf", "Netto Marken-Discount", "Netto Dierdorf",
        "https://wochenprospekt.netto-online.de/",
        "weekly_prospect", "store_specific", "Offizieller digitaler Netto-Wochenprospekt; storeid=6822.", True, True,
    ),
    RetailSource(
        "netto_oberhonnefeld", "Netto Marken-Discount", "Netto Oberhonnefeld-Gierend",
        "https://wochenprospekt.netto-online.de/",
        "weekly_prospect", "store_specific", "Offizieller digitaler Netto-Wochenprospekt; storeid=2648.", True, True,
    ),
    RetailSource(
        "aldi_dierdorf", "ALDI SÜD", "ALDI SÜD Dierdorf",
        "https://www.aldi-sued.de/angebote", "prospect_discovery", "regional_chain",
        "Offizielle ALDI-SÜD-Angebotsseite; Filialregion wird als Zielkontext gespeichert.", True, False,
    ),
    RetailSource(
        "aldi_oberhonnefeld", "ALDI SÜD", "ALDI SÜD Oberhonnefeld-Gierend",
        "https://www.aldi-sued.de/angebote", "prospect_discovery", "regional_chain",
        "Offizielle ALDI-SÜD-Angebotsseite; Filialregion wird als Zielkontext gespeichert.", True, False,
    ),
    RetailSource(
        "edeka_puderbach", "EDEKA", "EDEKA Fellenzer",
        "https://www.edeka.de/maerkte/071378/", "prospect_discovery", "store_specific",
        "Offizielle EDEKA-Marktseite zur Discovery des marktbezogenen PDF-Prospekts.", True, True,
        ("https://edeka-fellenzer.de/angebote/",),
    ),
    RetailSource(
        "lidl_puderbach", "Lidl", "Lidl Puderbach",
        "https://www.lidl.de/c/online-prospekte/s10005610", "prospect_discovery", "local_target",
        "Requires confirmed Puderbach store context before import; Lidl benchmark remains paused.", True, False,
    ),
]

SOURCE_BY_KEY = {source.key: source for source in SOURCES}
SOURCE_BY_STORE = {source.store_name: source for source in SOURCES}

RETAILER_FALLBACK_URLS = {
    "Lidl": "https://www.lidl.de/c/online-prospekte/s10005610",
    "ALDI SÜD": "https://www.aldi-sued.de/angebote",
    "EDEKA": "https://www.edeka.de/",
    "Netto Marken-Discount": "https://wochenprospekt.netto-online.de/",
    "REWE": "https://www.rewe.de/angebote/",
    "PENNY": "https://www.penny.de/angebote",
}


def source_for_store(store_name: str) -> RetailSource | None:
    return SOURCE_BY_STORE.get(store_name)


def _normalized_known_source(source: RetailSource) -> RetailSource:
    url = source.url
    if source.retailer == "EDEKA":
        url = _normalize_edeka_market_url(url)
    elif source.retailer == "REWE":
        url = _normalize_rewe_collection_url(url)
    if url == source.url:
        return source
    return RetailSource(
        key=source.key,
        retailer=source.retailer,
        store_name=source.store_name,
        url=url,
        mode=source.mode,
        locality=source.locality,
        notes=source.notes,
        supports_products=source.supports_products,
        store_specific=source.store_specific,
        alternate_urls=source.alternate_urls,
    )


def source_for_store_record(store) -> RetailSource | None:
    """Return a source for a concrete Store, including newly discovered markets.

    Hand-tuned registry entries still win. New markets can use a store-specific
    URL discovered from OSM/admin data or a retailer-level fallback. They start
    unverified and therefore remain QA-only until explicitly released.
    """
    known = SOURCE_BY_STORE.get(store.name)
    if known:
        return _normalized_known_source(known)
    url = (store.source_url or "").strip() or RETAILER_FALLBACK_URLS.get(store.retailer)
    if not url:
        return None
    if store.retailer == "EDEKA":
        url = _normalize_edeka_market_url(url)
    elif store.retailer == "REWE":
        url = _normalize_rewe_collection_url(url)
    store_specific = bool((store.source_url or "").strip())
    return RetailSource(
        key=f"auto_{store.retailer.lower().replace(' ', '_').replace('-', '_')}_{store.id}",
        retailer=store.retailer,
        store_name=store.name,
        url=url,
        mode="store_page" if store_specific else "prospect_discovery",
        locality="store_specific" if store_specific else "regional_chain",
        notes="Automatisch aus Markt-Onboarding erzeugte Quelle.",
        supports_products=True,
        store_specific=store_specific,
    )
