# BR-1C – Retailer Product Identity

## Ziel

BR-1C trennt drei Identitätsebenen sauber:

1. `MasterProduct` – kanonisches Spareno-Produkt
2. `RetailerProduct` – händlerweit wiedererkennbare Produktidentität
3. `SourceProduct` – konkrete Store-/Source-Provenienz einer Beobachtung

Dadurch können Preis- und Angebotsbeobachtungen aus mehreren Filialen zusammengeführt werden, ohne Store-Provenienz zu verlieren oder schwache IDs fälschlich als händlerweite Identität zu behandeln.

## Grundregel

> Store ist Provenienz, nicht Produktidentität. Händlerweite Identität entsteht nur aus starker, belegbarer Evidenz.

## Starke Identität

BR-1C akzeptiert zunächst nur:

- gültige GTIN/EAN mit korrekter Prüfziffer
- explizites `retailer_product_id`
- `external_product_id` nur, wenn `external_product_scope` ausdrücklich `retailer`, `chain` oder `retailer_wide` ist

Die Identität wird innerhalb eines Händlers gebildet. Dieselbe GTIN bei REWE und EDEKA ergibt daher zwei `RetailerProduct`-Zeilen, die aber auf dasselbe `MasterProduct` zeigen können.

## Nicht automatisch stark

Folgende Felder werden ohne expliziten Scope nicht händlerweit zusammengeführt:

- `external_product_id`
- `product_id`
- `article_id`
- `sku`
- source-spezifische IDs
- Produktname
- Packungslabel
- Store-Nähe oder Store-ID

Diese Werte dürfen weiterhin die `SourceProduct`-Provenienz stabilisieren, sind aber allein kein Beweis für händlerweite Produktgleichheit.

## Konfliktverhalten

Wenn dieselbe starke Händleridentität bereits einem anderen `MasterProduct` zugeordnet ist, wird im Collector niemals automatisch umgehängt.

Das bedeutet:

- bestehende kanonische Zuordnung bleibt unverändert
- neue `SourceProduct`-Provenienz darf bestehen
- sie erhält in diesem Konfliktfall keine neue `retailer_product_id`
- historische `PriceObservation`-Zeilen bleiben unverändert

Ein späterer Admin-/Matching-Sprint kann solche Fälle gezielt prüfen und kuratieren.

## Migration

Migration `20260909_03` ist additiv:

- neue Tabelle `retailer_products`
- nullable `source_products.retailer_product_id`
- passende Indizes/FK
- kein historisches Auto-Merging
- kein Rewrite vorhandener SourceProduct-IDs
- kein Rewrite vorhandener PriceObservation-IDs oder FKs

Bestehende BR-1A/BR-1B-Daten bleiben daher vollständig erhalten. Alte SourceProducts werden erst bei einer neuen Beobachtung mit starker Evidenz an ein RetailerProduct gebunden.

## Warum kein automatischer historischer Backfill?

Die bisherige `external_product_id` kann je nach Collector store-, source- oder händlerweit sein. Ein pauschaler Backfill würde diese Semantik erraten und könnte reale Produkte falsch fusionieren.

BR-1C folgt deshalb demselben Sicherheitsprinzip wie die Marktidentität:

> Keine Fusion ohne starken Identitätsbeweis.

## Beispiele

### Gleiche GTIN, gleicher Händler, zwei Stores

- REWE Store A → SourceProduct A
- REWE Store B → SourceProduct B
- beide → ein gemeinsames REWE RetailerProduct
- RetailerProduct → ein MasterProduct

### Gleiche GTIN, unterschiedliche Händler

- REWE → eigenes RetailerProduct
- EDEKA → eigenes RetailerProduct
- beide können → dasselbe MasterProduct

### Gleiche generische external_product_id ohne Scope

- keine händlerweite Fusion
- SourceProducts bleiben getrennt

### Konflikt

- vorhandenes REWE RetailerProduct `GTIN 400...` → MasterProduct A
- neue Beobachtung mit derselben GTIN wird als MasterProduct B gematcht
- RetailerProduct wird nicht auf B umgehängt
- neue SourceProduct-Zeile bleibt ohne RetailerProduct-Link

## Abgrenzung

BR-1C macht bewusst noch nicht:

- automatische MasterProduct-Merges
- Admin-Konfliktauflösung
- Produktbild-Konsolidierung
- semantisches Fuzzy-Matching als starke Identität
- EAN-Recherche aus externen Produktdatenbanken

Diese Themen bauen auf der jetzt stabilen Identitätshierarchie auf.
