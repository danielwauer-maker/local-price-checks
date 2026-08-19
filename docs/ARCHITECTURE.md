# Architektur

## Laufzeit

FastAPI + Jinja2 + SQLAlchemy + SQLite für den lokalen MVP. Die Anwendung ist Docker-fähig und die Datenbank liegt in einem persistenten Volume.

## Datenfluss

Offizielle Händlerquelle / Prospekt -> Collector/Parser -> Qualitätsgate -> normalisierte Produkte/Angebote -> Nutzerfilter (Standort, Radius, Markt-Favoriten) -> Produktfavoriten/Einkaufsliste -> Sparplan.

### Collection-Lifecycle

Ein strukturierter Lauf besitzt einen expliziten, für alle Entry-Points identischen Lifecycle:

1. Markt und offizielle Quelle auflösen.
2. Quelle genau einmal abrufen und ein kanonisches Collector-Ergebnis erzeugen.
3. Den retailer-spezifischen Artifact-Adapter mit diesem Ergebnis aufrufen.
4. Rohangebote validieren, normalisieren und als deduplizierte `Offer`-Zeilen importieren.
5. Jede konkrete Fundstelle als `OfferOccurrence` erhalten.
6. Das unveränderliche `ProspectArchive` nach dem Import mit `OfferProvenance` finalisieren.
7. Strukturierte Laufdiagnosen und den Gesundheitsstatus speichern.

Der Artifact-Adapter wird als Abhängigkeit an `collect_structured_for_store` übergeben. Es gibt keine beim Import oder App-Start ausgetauschten Funktionsreferenzen. Dadurch laufen Admin-Background-Job, Scheduler und API über denselben Codepfad.

Für REWE rendert der Adapter ausschließlich das bereits erfolgreich geladene `result["raw"]` als gekennzeichnetes Web-Abbild. Eine zweite Navigation zur Händlerseite ist im Collection-Pfad nicht zulässig. Schlägt nur die Archivierung fehl, bleiben valide Angebote gemäß Recall-first erhalten; der Lauf wird jedoch `warning` statt `success` und meldet `archive_created=false`.

### Persistenzgrenzen

- `Offer` ist die deduplizierte öffentliche Preiszeile.
- `OfferOccurrence` bewahrt jede unterschiedliche Rohfundstelle und den Original-Untertext.
- `ProspectArchive` ist die unveränderliche, per SHA256 identifizierte Quellkopie.
- `OfferProvenance` verbindet ein Angebot mit Archive und exakter Seite.
- `Prospect` zeigt auf das aktuell auswählbare Dokument im Admin-/Public-Layer.

Support-Exporte enthalten Metadaten zu `Prospect`, `ProspectArchive` und `OfferProvenance`, aber keine PDF-Binärdaten oder Secrets. Damit sind DB-/Dateisystem-Entkopplungen aus einem Produktionspaket erkennbar.

## Datenschutz V1

Keine Browser-Geolocation. Gespeichert werden lediglich PLZ, Ort, daraus aufgelöste ungefähre Koordinaten, Radius und ausgewählte Märkte.

## Datenbankentwicklung

SQLite bleibt für lokale Entwicklung und ersten kleinen Webbetrieb. Bei Mehrbenutzer-/Haushaltsbetrieb ist PostgreSQL als nächster Schritt vorgesehen.
