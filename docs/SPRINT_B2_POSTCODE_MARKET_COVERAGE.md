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

## B2.2: Polygonkarte und belastbarer Soll-/Ist-Abgleich

### Geometriequelle, Cache und Lizenz

Die PLZ-Polygone stammen aus OpenStreetMap und wurden über die Nominatim-
GeoJSON-Ausgabe exakt je PLZ abgerufen. OpenStreetMap-Daten stehen unter der
[Open Database License 1.0](https://www.openstreetmap.org/copyright). Die im
Admin sichtbare Attribution lautet `© OpenStreetMap contributors, ODbL 1.0`.

Der Repository-Cache `app/static/postcode_geometries_b2.geojson` enthält nur
die acht initial freigegebenen PLZ, nicht einen Deutschland-Gesamtdatensatz.
Stand des Cache ist 2026-08-26. Jedes Feature speichert zusätzlich den
konkreten OSM-Typ und die OSM-ID, zum Beispiel
`osm:nominatim:relation/1130659@2026-08-26`. Die Polygone wurden ausschließlich
für eine schlanke Admin-Darstellung geometrisch vereinfacht; die abgeleiteten
Geodaten bleiben unter ODbL.

Beim Start werden nur fehlende Geometrien aus diesem Cache ergänzt. Bereits
gespeicherte, neuere Geometrien werden nicht überschrieben. Ein Admin kann
eine einzelne PLZ explizit aktualisieren oder neu importieren. Dabei gelten die
[Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/),
ein identifizierender User-Agent, genau eine Anfrage für die ausgewählte PLZ
und lokales Caching. Es gibt keinen Bulk-Download, keine Autocomplete-Suche und
keine Abhängigkeit der Kartenanzeige vom Geometrie-Netzwerkzugriff. Scheitert
der Provider, bleibt der vorhandene Cache unverändert nutzbar.

Die Kartenbibliothek ist das bereits im Projekt verwendete Leaflet 1.9.4. Die
Karte und die Tabellenansicht werden aus denselben `CoveragePostalCode`-Zeilen
und denselben serverseitig berechneten Reconciliation-Ergebnissen erzeugt.

### Händleradapter

`app/retailer_store_sources.py` definiert eine gemeinsame Adapter-Schnittstelle
für erwartete Filialen. Jeder Adapter liefert strukturierte Marktidentität,
Quellentyp, Quell-URL und einen expliziten Status:

- `supported`: Die Quelle kann für diese PLZ als vollständig bewertet werden.
- `manual_verification_required`: Einzelne offizielle Marktseiten sind
  belastbar, aber die Vollständigkeit des Filialbestands ist nicht automatisch
  beweisbar.
- `source_unavailable`: Die Quelle konnte nicht ausgewertet werden.

Aktueller Stand:

| Händler | Automatisch belastbare Einzelmarktquelle | Vollständigkeit pro PLZ |
| --- | --- | --- |
| REWE | Kuratierte offizielle Marktseite für Dierdorf | manuell im offiziellen Filialfinder prüfen |
| Lidl | Kuratierte offizielle Marktseite für Puderbach | manuell im offiziellen Filialfinder prüfen |
| EDEKA | Kuratierte offizielle Marktseite für Puderbach | manuell im offiziellen Filialfinder prüfen |
| ALDI SÜD | keine stabile maschinenlesbare Schnittstelle integriert | manuell prüfen |
| Netto Marken-Discount | keine stabile maschinenlesbare Schnittstelle integriert | manuell prüfen |
| PENNY | keine stabile maschinenlesbare Schnittstelle integriert | manuell prüfen |

Die offiziellen Filialfinder werden verlinkt, aber nicht über fragile HTML-
Selektoren als vermeintlich vollständige API gescrapt. Ein einzelner offiziell
belegter Markt wird als `official:<adapter>` im bestehenden Candidate-Staging
geführt. Das bestätigt die Quelle dieses konkreten Markts, nicht die
Vollständigkeit der PLZ. Tests können denselben Adaptervertrag mit vollständig
deterministischen Quellen implementieren; CI greift nie auf Händlerseiten oder
Overpass zu.

### Reconciliation und Statussemantik

`app/postcode_reconciliation.py` trennt erwartete offizielle Kandidaten von
OSM-Discovery-Kandidaten. Ein Match verlangt dieselbe PLZ, denselben
normalisierten Händler, passenden Ort und passende vollständige Adresse sowie
eine Koordinatenabweichung innerhalb des konfigurierten Grenzwerts.

Pro PLZ werden angezeigt:

- `expected`: Kandidaten aus konkreten offiziellen Händlerquellen
- `found`: unabhängig entdeckte/staged Kandidaten, aktuell OSM
- `address_verified`: gefundene Kandidaten mit bestätigter Adresse
- `coordinates_verified`: gefundene Kandidaten mit bestätigtem Pin
- `official_verified`: gefundene Kandidaten mit eigener oder gematchter
  offizieller Quellenbestätigung
- `promoted`: bereits zugeordnete bzw. vorhandene Stores der exakten PLZ
- fehlende erwartete und zusätzliche OSM-Kandidaten

Status:

- `disabled`: PLZ nicht aktiviert; grau
- `incomplete`: mindestens ein konkret erwarteter Markt fehlt; rot
- `verification_pending`: Kandidaten sind vorhanden, aber Identitäts-Gates,
  Promotion oder die Prüfung eines zusätzlichen Kandidaten fehlen; gelb
- `complete`: Soll und Ist stimmen überein, alle drei Identitäts-Gates und die
  Promotion sind vollständig, und alle beteiligten Quellen bestätigen ihre
  Vollständigkeit; grün
- `source_unavailable`: Vollständigkeit kann wegen fehlender oder nur manuell
  prüfbarer Händlerquelle nicht behauptet werden; rot
- `no_expected_stores`: vollständig unterstützte Quellen melden keine
  erwarteten Märkte; grau

OSM allein kann niemals `complete` erzeugen. Zusätzliche OSM-Kandidaten werden
explizit als Review-Fall ausgewiesen und nicht still ignoriert.

### Adress- und Positionsverifikation

Bei mehreren Quellen wird die konkrete offizielle Händlerquelle als Referenz
bevorzugt; OSM bleibt Discovery/Cross-Check. Verglichen werden zwingend:

- fünfstellige PLZ
- Ort
- Händler
- vollständige Straße und Hausnummer
- Marktkoordinaten

Straßen-Schreibweisen wie `Straße`, `Strasse` und `Str.` werden nur für den
Identitätsvergleich normalisiert. Die berechnete Pin-Abweichung wird in Metern
im Verification-Hinweis gespeichert und im Admin angezeigt. Der Standardwert
ist 250 Meter und kann mit `STORE_COORDINATE_TOLERANCE_M` konfiguriert werden.
Eine größere Abweichung setzt `coordinates_verified=false`; fehlende oder
abweichende Adresse, Ort, PLZ oder Händler setzen auch das Adress-Gate nicht.
Ohne offizielle Referenz bleibt der bestehende exakte Nominatim-Cross-Check
verfügbar.

### Promotion- und Quality-Gates

Die B2.1-Regel bleibt zentral in `candidate_ready_for_promotion`:

1. vollständige Adresse/Ort und valide fünfstellige PLZ
2. `address_verified=true`
3. `coordinates_verified=true`
4. `official_source_verified=true`
5. Kandidat ist nicht abgelehnt

Promotion setzt `benchmark_verified` niemals. Ein übernommener Markt bleibt
damit intern/QA, bis die getrennte Angebots- und Benchmark-Qualitätsprüfung ihn
explizit freigibt.

### Schema und bekannte Grenzen

B2.2 verwendet ausschließlich die mit Migration `20260825_03` vorhandenen
Felder `center_lat`, `center_lng`, `geometry_source` und `geometry_geojson`
sowie das bestehende Candidate-Staging. Es ist keine neue Alembic-Revision und
keine destructive Migration erforderlich.

Bekannte Grenzen:

- Der initiale Geometriecache umfasst bewusst nur acht PLZ. Weitere Gebiete
  werden einzeln importiert und gecacht.
- Für keinen der sechs Händler wird derzeit eine undokumentierte oder fragile
  Webschnittstelle als vollständige Filial-API ausgegeben. Daher bleibt der
  Gesamtstatus bei nur partiell belegten Händlerquellen bewusst rot.
- OSM- und Händlerdaten können zeitlich auseinanderliegen. Abweichungen werden
  als QA-Arbeit sichtbar und niemals automatisch als korrekt aufgelöst.
- Kartenkacheln und Leaflet-CDN benötigen für die visuelle Basiskarte Netzwerk;
  die gespeicherten Polygone und die Tabellen-/Statusdaten bleiben serverseitig
  auch bei Ausfall der Geometriequelle verfügbar.

## B2.3: Market Activation & Quality Gate

Die Identitätsprüfung, Datenqualität und öffentliche Freigabe bleiben getrennte
Entscheidungen. Der zentrale Lifecycle lautet: `discovered` →
`identity_verified` → `promoted` → `scrape_pending`/`scrape_failed` →
`quality_review` → `quality_passed` → `public`; ein Admin kann einen Markt in
`suspended` überführen. Discovery und Promotion veröffentlichen nie automatisch.

Nach einer Promotion registriert `StoreActivationState` die bestätigte
Marktidentität. Erst dann darf ein Admin einen Test-Scrape starten. Dieser nutzt
den vorhandenen Store-Collector und dessen `CollectionRun` sowie
`CollectionQualitySnapshot`; es gibt keine zweite Extraktionsengine. Start,
Ende, Dauer, Quelle, Roh-/gültige Angebote, Preis- und Einheitsabdeckung,
Dubletten, ungültige/Nicht-Produkte, Prospektdatum/-seite und Fehler bleiben
nachvollziehbar gespeichert. `StoreQualityAssessment` hält pro Testlauf die
strukturierte, historische Gate-Bewertung.

`assess_store_quality` bewertet transparent sechs gewichtete Checks:

- bestätigte Identität (15 Punkte)
- erfolgreicher Test-Scrape (20)
- mindestens 10 gültige Angebote (20)
- mindestens 80 % der gültigen Angebote mit Preis (20)
- höchstens 10 % Dubletten bezogen auf Rohzeilen (10)
- höchstens 20 % ungültige/Nicht-Produkte bezogen auf Rohzeilen (15)

Die vier Zahlen sind über `STORE_QUALITY_MIN_VALID_OFFERS`,
`STORE_QUALITY_MIN_PRICE_COVERAGE_PCT`,
`STORE_QUALITY_MAX_DUPLICATE_RATE_PCT` und
`STORE_QUALITY_MAX_INVALID_RATE_PCT` konfigurierbar. Ergebnis, Score, einzelne
Checks, Messwerte, Fehlergründe und Warnungen werden angezeigt und gespeichert;
es wird keine allgemeine Qualitätsquote behauptet.

`store_ready_for_publication` verlangt bestätigte Identität, den letzten
erfolgreichen Testlauf, dessen bestandenes Assessment und das Fehlen einer
manuellen Sperre. Auch `quality_passed` veröffentlicht noch nicht: Erst der
explizite Admin-Schritt setzt den Lifecycle auf `public` und das bestehende
Kompatibilitätsfeld `benchmark_verified=true`. Normale Markets-, Angebots-,
Favoriten-, Umkreis-, Startseiten-, Prospekt- und Einkaufslistenpfade verwenden
nur `active=true AND benchmark_verified=true`. Historische Bestandsmärkte mit
diesen Flags werden bei der additiven Migration als `public` übernommen.

Suspend setzt `benchmark_verified=false`, lässt Store, Angebote, Testläufe und
Assessments jedoch bestehen. Reactivate hebt nur die Sperre auf und führt bei
weiter gültigem Gate zu `quality_passed`; eine erneute Veröffentlichung bleibt
ein eigener Admin-Schritt. Die Migration `20260826_01` ergänzt ausschließlich
`store_activation_states` und `store_quality_assessments` und ist für SQLite
und PostgreSQL ausgelegt.
