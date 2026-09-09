# BR-1A – Daily Data Steward & Price Observation Foundation

## Ist-Architektur und Wiederverwendung

BR-1A erweitert die vorhandene Collector-Kette und baut keinen zweiten Scheduler.

- `app/scheduler.py` bleibt die authoritative APScheduler-Integration mit Zeitzone `Europe/Berlin`, Cron-Stunde/-Minute, `max_instances=1` und `coalesce=True`.
- `CollectionRun` bleibt der technische Lauf eines Marktes; `CollectionQualitySnapshot` bleibt dessen strukturierte QA-/Benchmark-Auswertung.
- `Offer` bleibt der deduplizierte, öffentlich lesbare Angebotsbestand.
- `OfferOccurrence` bewahrt konkrete Prospektvorkommen und Provenance; `OfferPriceReference` bewahrt beworbene Vergleichspreise.
- `NormalPriceObservation` und die Medianauflösung über 120 Tage bleiben bestehen. BR-1A ersetzt diese Logik nicht.
- Die EDEKA-Collection bleibt auf dem produktiven Central-plus-local-Pfad in `edeka_live_collector`; Marktidentität, Public Gate und physische Markt-Deduplizierung bleiben unverändert.
- Golden Dataset, Prospect Audit, Media-Admin, Collector-Admin, Quality Gate und Audit-Daten bleiben die spezialisierten Review-Werkzeuge.

## Erkannte Risiken und vermiedene Redundanzen

Vor BR-1A wurde ein Collector-Ergebnis importiert, bevor eine dynamische Volumenanomalie bewertet werden konnte. Ein drastisch kollabierter Lauf hätte damit zwar einen schlechten Benchmark erhalten, seine Rows aber bereits in den produktiven Tabellen hinterlassen. Der neue Guard läuft vor `import_collected_offers`.

`OfferPriceReference` und `NormalPriceObservation` dürfen nicht zu einer allgemeinen Preistabelle verschmolzen werden: Ein `UVP`, `RRP`, `statt` oder sonstiger beworbener Referenzwert ist Provenance, aber keine Beobachtung des normalen Regalpreises. Deshalb ergänzt BR-1A eine allgemeine Faktenhistorie und lässt die spezialisierten Tabellen bestehen.

## Datenmodell

### `SourceProduct`

Ein Händler-/Quellprodukt bildet die stabile Identität einer gelieferten Produktdarstellung auf ein `MasterProduct` ab. Der Identity Key ist SHA-256 über:

`retailer | store_id | source_key | external_product_id-or-normalized_master_key`

Vorhandene belastbare Händler-IDs (beispielsweise Lidl Product IDs) werden bevorzugt. Fehlende IDs werden nicht erfunden; dann ist der bestehende normalisierte Produkt-Key die deterministische Fallback-Identität.

### `PriceObservation`

Eine Price Observation ist append-only. Unterstützte Typen:

- `NORMAL`
- `PROMOTION`
- `ADVERTISED_REFERENCE`
- `LOYALTY`
- `COUPON`
- `MULTIBUY`
- `UNKNOWN`

Der Retry-/Idempotency-Key ist SHA-256 über UTC-Beobachtungstag, Master Product, Store, Source Key, belastbare External ID, Price Type, Preis, Unit Price/Unit, Validity und Fakt-Suffix. Ein technischer Retry desselben täglichen Fakts erzeugt keine Duplikate; ein späterer Kalendertag fügt eine neue historische Beobachtung hinzu. Die Tabelle enthält CollectionRun-Provenance, Confidence und Source URL und besitzt Indizes für die geplanten Millionenzeilen-Hot-Paths.

### `DailyCollectionRun`

Pro Berliner Kalendertag existiert genau ein logischer Gesamt-Run. Ein manueller Retry aktualisiert denselben Datensatz und erzeugt keine parallele Daily-Run-Hierarchie. Er aggregiert geplante, erfolgreiche, fehlgeschlagene und blockierte Märkte sowie Offers, neue Produkte, Preis-/Normalpreis-/Referenzbeobachtungen, Match-, Bild- und Preisabdeckung, Warnungen, Blocker und die zugehörigen `CollectionRun`-IDs.

## Price Semantics

Collector-Offerpreise werden ausschließlich als `PROMOTION`, `MULTIBUY` oder `COUPON` beobachtet. App-/Loyalty-Preise werden separat als `LOYALTY` gespeichert. Gelieferte `regular_price`-Werte werden als `ADVERTISED_REFERENCE` gespeichert.

Keiner dieser Werte erzeugt automatisch eine `NormalPriceObservation`. Der bestehende Backfill akzeptiert nur noch den expliziten Provenance-Typ `retailer_regular`; historische `offer_ref:uvp`, `offer_ref:rrp`, `offer_ref:regular` und `offer_ref:was_price` werden bei der Normalpreisauflösung nicht verwendet. Existiert keine belastbare Beobachtung, bleibt der Status `unknown`. Bestehende Offer-Reference-Payloads und Badges bleiben lesbar.

## Daily Run Flow und Collapse Guard

1. Der Scheduler lädt nur aktive und `benchmark_verified` physische Märkte und kollabiert Aliase mit der bestehenden Identitätslogik.
2. EDEKA verwendet weiterhin seinen dedizierten produktiven Collector; andere Händler verwenden den bestehenden Dispatcher.
3. Der Rohbestand wird gegen die letzten erfolgreichen Markt-Runs und den bestehenden Retailer Floor geprüft.
4. Standardmäßig: fünf letzte Runs, mindestens drei Historienwerte, Warning unter 70 Prozent des Medians, Block unter 40 Prozent. Alle Werte sind zentral per Environment konfigurierbar.
5. Der strengere Zustand aus historischem Guard und vorhandenem retailer-spezifischem Floor gewinnt.
6. `blocked` beendet den Lauf vor Offer-/Produkt-/Preis-Persistenz. Vorhandene produktive Daten werden nicht ersetzt oder gelöscht. Die Diagnose ist deterministisch, z. B. `offer_count_collapse: 21 vs recent median 178`.
7. Eine Markt-Exception wird protokolliert; weitere Märkte laufen weiter.

## Admin Data Operations

`/admin/datenstatus` ist das zentrale serverseitige Cockpit. Es zeigt KPI Cards, critical-first Attention Items, Marktstatus mit Baseline/Abdeckung/Quality und letzte Daily Runs. Es verwendet gebündelte Queries statt marktweiser N+1-Abfragen. Aktionen verlinken ausschließlich auf bestehende sichere Werkzeuge oder starten den vorhandenen Collector. Es gibt keine automatische Freigabe, Reparatur oder Produktzusammenführung.

Die Review-Sicht leitet Fälle aus vorhandenen Runs, Quality Metrics, Prospect Price Anchors, Media Coverage und Price Observations ab. Dazu gehören Collector Failure/Collapse, niedrige Counts, unsichere Produktnamen, fehlende/unplausible Preise, Gültigkeitsprobleme, Referenzkonflikte, fehlende Bilder und mögliche Duplikate.

## AI-Agent-Grenze

Ein späterer Agent darf die deterministisch erzeugten Runs, Metrics und Review-Fälle lesen, erklären, ranken und zusammenfassen. Er darf niemals Preisfakten oder Normalpreise schreiben, unsichere Produkte mergen, Märkte veröffentlichen, Quality-/Collapse-Gates umgehen, Production Code verändern oder deployen. Der tägliche Pflichtlauf hat keine LLM-Abhängigkeit.

## Migration und Release-Sicherheit

Migration `20260909_01` ist additiv, SQLite-/PostgreSQL-kompatibel und folgt auf `20260903_01`. Sie erstellt drei neue Tabellen, Foreign Keys, Unique Constraints und Hot-Path-Indizes; vorhandene Preis-/Offer-Historie wird nicht verändert.

Das Production Schema Gate wird absichtlich nicht pauschal gelockert. Vor einem späteren Merge/Deployment ist ein separater kontrollierter Allowlist-Follow-up für exakt `migrations/versions/20260909_01_br1a_data_steward.py` und `app/data_operations_models.py` erforderlich. Ohne diesen Review bleibt das Deployment fail-closed.

## Bekannte Grenzen und BR-1B

BR-1A sammelt belastbare Fakten, baut aber noch keine 30-/90-/180-Tage-Deal-Score-Engine. Match Rate verwendet die bestehende Import-/Match-Semantik; ein dedizierter probabilistischer Matcher bleibt Review-only. BR-1B sollte historische Quellen backfillen, Normalpreis-Beobachtungsquellen explizit zulassen, per-Run Detailseiten und persistente Review-Acknowledgements ergänzen und anschließend robuste Zeitfensterstatistiken vorbereiten.
