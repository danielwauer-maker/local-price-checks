# MVP Scope

## V1

- Mobile-first Webapp
- Hauptstandort nur via PLZ + Ort; keine automatische Standortfreigabe
- Radius um Hauptstandort
- Nutzer wählt bevorzugte Märkte
- Nur favorisierte, im Radius liegende und benchmark-freigegebene Märkte werden verglichen
- Produktfavoriten
- Einkaufsliste mit Mengen
- Barcode/GTIN über Handykamera oder manuelle Eingabe
- aktuelle und bereits bekannte kommende Angebote
- Preisvergleich
- Sparplan / Mehrmarktvergleich

## Händler-Gate

Produktiv freigegeben werden Händler/Standorte erst nach >= 99 % Referenzqualität.

Stabiler KW33-Referenzstand:

- REWE Dierdorf: 227/227
- Netto: 359/361
- ALDI SÜD: 170/174
- Gesamt: 756/762 = 99,21 %

EDEKA und Lidl bleiben bis zum eigenen >=99-%-Benchmark außerhalb des V1-Vergleichs.
REWE Straßenhaus ist im Datenmodell angelegt, aber bis zur vollständigen Marktbenchmark noch nicht als benchmark_verified markiert.

## Später

- Benutzerkonten und Haushalte
- gemeinsame Einkaufsliste
- Bestand
- MHD-Chargen und Ablauf-Erinnerungen
- intelligente Nachkaufempfehlungen
- EDEKA/Lidl nach Qualitätsfreigabe
