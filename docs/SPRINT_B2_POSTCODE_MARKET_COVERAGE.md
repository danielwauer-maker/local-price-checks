# Sprint B2 – PLZ-Freigabe und Marktabdeckung

## Ziel

Das Adminbackend bekommt eine klickbare Deutschlandkarte mit 5-stelligen PLZ-Gebieten. Eine aktivierte PLZ stößt die Marktermittlung für die unterstützten Händler an. Gefundene Märkte werden zunächst als **Discovery Candidates** geführt und erst nach Prüfung in den produktiven Marktbestand übernommen.

Initial freigegebene PLZ:

- 65618
- 65611
- 65606
- 57614
- 56305
- 56269
- 56316
- 57610

## Zentrale Sicherheitsregel

**PLZ freigegeben != Markt öffentlich.**

Ein Markt darf erst für automatische Angebotsläufe verwendet werden, wenn seine Identität belastbar ist. Ein Markt darf erst Nutzerangebote liefern, wenn zusätzlich die Angebotsqualität freigegeben wurde.

Pipeline:

`PLZ aktiviert -> Markt entdeckt -> Adresse geprüft -> Koordinaten geprüft -> offizielle Händlerquelle geprüft -> Markt übernommen -> Test-Scrape -> Qualitätsgate -> öffentlich`

## Markt-Identität

Für jeden Kandidaten werden mindestens gespeichert:

- Händler
- Marktname
- vollständige Straße und Hausnummer
- 5-stellige PLZ
- Ort
- Latitude/Longitude
- Discovery-Quelle und External-ID
- Händler-/Quell-URL
- Prüfstatus für Adresse
- Prüfstatus für Koordinaten
- Prüfstatus für offizielle Händlerquelle
- später zugeordnete `stores.id`

### Adresse

Eine OSM-Angabe mit fehlender Straße/Hausnummer reicht **nicht** für automatische Freigabe. Platzhalteradressen dürfen nicht in `Store` promoviert werden.

### Koordinaten

Ein Karten-Pin wird nicht allein aus dem Mittelpunkt einer PLZ oder eines Orts erzeugt. Die Koordinate muss zur konkreten Marktadresse gehören. Vor Promotion wird die Position gegen die vollständige Adresse gegengeprüft. Größere Abweichungen werden als QA-Fall markiert statt still übernommen.

### Offizielle Händlerquelle

OpenStreetMap/Overpass ist Discovery-Quelle, aber nicht alleinige Autorität. Für REWE, Lidl, ALDI SÜD, Netto Marken-Discount, EDEKA und PENNY soll B2 Händler-Adapter bzw. verifizierbare Händlerquellen nutzen, um Marktadresse/Markt-ID gegenzuprüfen. Abweichungen bleiben im Backend sichtbar.

## Soll-/Ist-Abgleich je PLZ

Die Coverage-Ansicht muss je aktivierter PLZ zeigen:

- Anzahl gefundener Märkte
- Händlerverteilung
- Kandidaten mit vollständiger Adresse
- Kandidaten mit verifizierten Koordinaten
- Kandidaten mit offizieller Quellenbestätigung
- fehlende/unklare Märkte
- promovierte Märkte
- letzter Discovery-Zeitpunkt

Damit kann nicht nur geprüft werden, **welche** Märkte gefunden wurden, sondern auch ob erwartete Filialen fehlen.

## PLZ-Geometrie

Die vom Nutzer genannte ArcGIS-Karte dient als UX-Vorbild. Die Geometriedaten werden nicht ungeprüft übernommen. Für die Implementierung wird ein klar lizenzierter, versionierter PLZ-Polygon-Datensatz verwendet und lokal/cachebar über eine Backend-Schnittstelle ausgeliefert. Die Datenquelle und Attribution werden im Admin-UI sichtbar dokumentiert.

Eine geeignete technische Alternative sind aus OpenStreetMap extrahierte PLZ-Grenzen unter ODbL. Die Boundary-Quelle wird als Provider gekapselt, damit sie später aktualisiert oder ersetzt werden kann.

## Angebotsqualität

Nach erfolgreicher Marktidentität folgt ein Test-Scrape. Öffentliche Freigabe erfolgt erst nach einem separaten Quality Gate. Vorgesehene Kennzahlen:

- Anteil Angebote mit gültigem Preis
- Anteil plausible Produktnamen
- Anteil mit Packungsgröße/Einheit, wenn im Prospekt vorhanden
- Gültigkeitszeitraum vorhanden und plausibel
- Prospektseite/Quelle nachvollziehbar
- Dublettenquote
- Nicht-Produkt-/Werbetext-Quote
- Collector-Fehlerrate

Die Detailgrenzen werden im Scrape-/Quality-Sprint finalisiert. B2 speichert und visualisiert die Gate-Zustände, ohne eine vermeintliche 100%-Qualität vorzutäuschen.
