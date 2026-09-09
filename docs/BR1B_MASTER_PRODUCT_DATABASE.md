# BR-1B – Master Product Database V2

## Ziel

BR-1B erweitert Sparenos bestehende Produktidentität zu einem belastbaren kanonischen Produktkatalog, ohne die bereits produktiv verwendeten IDs oder historischen Preisbeobachtungen umzuschreiben.

Grundprinzip:

> Unvollständige, belegbare Produktdaten sind besser als erfundene Stammdaten.

## Identität bleibt stabil

`MasterProduct` bleibt die kanonische Produktidentität. Bestehende Referenzen aus Angeboten, Einkaufslisten, Favoriten, Medien, Barcodes und Preisbeobachtungen bleiben unverändert.

BR-1B ersetzt `master_products` daher nicht, sondern ergänzt die 1:1-Tabelle `master_product_profiles`.

## Verantwortlichkeiten

### MasterProduct

Stabile kanonische ID mit den bereits produktiv verwendeten Basisfeldern:

- Name
- Marke
- bisheriges Packungslabel
- `normalized_key`

### MasterProductProfile

Strukturierte, erweiterbare Stammdaten:

- kanonischer Name
- Hersteller
- Produktfamilie
- Variante
- paketunabhängiger Family Key
- Packungswert und Einheit
- Multipack-Anzahl
- Gesamtmenge
- Vergleichseinheit
- optionale Zutaten
- erweiterbare Eigenschaften
- Verifikationsstatus
- Confidence
- Datenquelle

Ein verifiziertes Profil wird von wiederkehrenden Collector-Läufen nicht automatisch überschrieben.

### ProductBarcode

Bleibt die GTIN/EAN-Zuordnung. Mehrere Barcode-Zeilen können auf dasselbe MasterProduct zeigen. BR-1B führt bewusst keine konkurrierende GTIN-Tabelle ein.

### ProductAlias

Bleibt die explizite Aliasauflösung auf ein MasterProduct.

### ProductAdminData / ProductCategory

Bleiben für Kategorie, Admin-Locks und manuelle Notizen verantwortlich.

### MediaAsset

Bleibt die Medienbibliothek. Die bevorzugte/alternative Bildlogik wird in BR-1D ausgebaut und nicht in BR-1B dupliziert.

### SourceProduct

Bleibt die in BR-1A eingeführte beobachtete Quellprodukt-Identität und ist aktuell store-spezifisch. BR-1B ändert diese Identität nicht rückwirkend.

Die bewusste Entscheidung, wann ein Händlerprodukt retailerweit, sourceweit oder storegebunden identisch ist, gehört in **BR-1C – Retailer Product Identity**. Dadurch verlieren wir keine bereits gesammelte Provenance und erzeugen jetzt keine zweite konkurrierende RetailerProduct-Abstraktion.

## Packungsdaten

Die erste BR-1B-Stufe parst nur eindeutig erkennbare Packungsangaben, z. B.:

- `500 g`
- `1 l`
- `6 x 0,33 l`

Komplexe oder werbliche Texte werden nicht geraten. Unbekannte Werte bleiben `NULL`.

## Backfill

Migration `20260909_02` legt für jedes bestehende MasterProduct sofort ein `MasterProductProfile` an.

Der initiale Backfill übernimmt nur sichere Basisdaten. Strukturierte Packungs- und Family-Daten werden anschließend idempotent durch den Katalog-Service ergänzt, wenn Produkte erneut verarbeitet werden.

Neue Produkte erhalten beim normalen Collector-Import sofort ein Profil.

## Verifikation

Profile starten standardmäßig mit:

- `verification_status = unverified`
- konservativer Confidence
- dokumentierter `data_source`

Spätere Admin-/Review-Sprints können ein Profil auf `verified` setzen. Ab diesem Zeitpunkt überschreibt ein Collector die kuratierten Profilfelder nicht mehr automatisch.

## Scope-Grenzen

Nicht Teil von BR-1B:

- retailerweite SourceProduct-Zusammenführung → BR-1C
- vollständige Product Media Library → BR-1D
- Admin Product Review UI → BR-1E
- Preis-Historienauswertung / Deal Score → BR-2
- neue Händler oder Collector-Rewrites

## Migrationssicherheit

`20260909_02` ist additiv:

- keine Änderung bestehender MasterProduct-IDs
- keine Änderung bestehender Offer-FKs
- keine Änderung bestehender PriceObservation-FKs
- keine Änderung der SourceProduct-Identität
- Downgrade entfernt nur die neue Profil-Tabelle

Vor einem späteren Production-Deployment muss die neue Schemaänderung wie bei BR-1A separat über den kontrollierten Production-Schema-Gate freigegeben werden.
