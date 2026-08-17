from dataclasses import dataclass


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
    # Paused for MVP: retained so work is not lost, but benchmark_verified on Store
    # keeps them out of user comparisons until their own >=99% gate is reached.
    RetailSource(
        "edeka_puderbach", "EDEKA", "EDEKA Fellenzer",
        "https://edeka-fellenzer.de/angebote/", "store_page", "store_specific",
        "Strukturierte Fellenzer-Angebotsseite; EDEKA parser benchmark remains paused.", True, True,
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
    "EDEKA": "https://edeka-fellenzer.de/angebote/",
    "Netto Marken-Discount": "https://wochenprospekt.netto-online.de/",
    "REWE": "https://www.rewe.de/angebote/",
}


def source_for_store(store_name: str) -> RetailSource | None:
    return SOURCE_BY_STORE.get(store_name)
