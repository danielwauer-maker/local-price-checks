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
    RetailSource("lidl_puderbach","Lidl","Lidl Puderbach","https://www.lidl.de/c/online-prospekte/s10005610","prospect_discovery","local_target","Prospekt-/Angebotsquelle; konkrete lokale Gültigkeit muss beim Artikel bestätigt werden."),
    RetailSource("edeka_puderbach","EDEKA","EDEKA Fellenzer","https://www.edeka.de/maerkte/071378/","store_page","store_specific","Marktseite mit Wochenangeboten und Link zum marktbezogenen Prospekt."),
    RetailSource("aldi_dierdorf","ALDI SÜD","ALDI SÜD Dierdorf","https://www.aldi-sued.de/angebote","prospect_discovery","regional_chain","Offizielle Angebotsseite mit aktuellem, nächstem und übernächstem Prospekt."),
    RetailSource("aldi_oberhonnefeld","ALDI SÜD","ALDI SÜD Oberhonnefeld-Gierend","https://www.aldi-sued.de/angebote","prospect_discovery","regional_chain","ALDI-SÜD-Angebote; Filialregion wird als Zielkontext gespeichert."),
    RetailSource("netto_dierdorf","Netto Marken-Discount","Netto Dierdorf","https://www.netto-online.de/filialen/dierdorf/koenigsberger-str-24/6822","store_page","store_specific","Filialseite enthält Filial-Angebote und Digitalen Wochenprospekt."),
    RetailSource("netto_oberhonnefeld","Netto Marken-Discount","Netto Oberhonnefeld-Gierend","https://www.netto-online.de/filialen/oberhonnefeld-gierend/ueber-dem-stellweg-25/2648","store_page","store_specific","Filialspezifische Quelle."),
    RetailSource("rewe_dierdorf","REWE","REWE:XL Hundertmark","https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/","store_page","store_specific","Marktseite mit Angebots-Highlights und Prospektzugang."),
]
RETAILER_FALLBACK_URLS={'Lidl':'https://www.lidl.de/c/online-prospekte/s10005610','ALDI SÜD':'https://www.aldi-sued.de/angebote','EDEKA':'https://www.edeka.de/angebote/','Netto Marken-Discount':'https://www.netto-online.de/angebote/','REWE':'https://www.rewe.de/angebote/','PENNY':'https://www.penny.de/angebote','Kaufland':'https://filiale.kaufland.de/angebote.html'}
