# Realtime & Performance Finalization

Stand: 29. August 2026. Alle Zahlen in diesem Dokument stammen aus ausgeführten Tests; nicht erhobene Vergleichswerte sind ausdrücklich als `nicht erhoben` markiert.

## Messaufbau

- Realtime: Playwright Chromium, zwei getrennte Browser-Kontexte/Geräte, echter HTTP-Pfad Browser → FastAPI → isolierte SQLite-Datei → Commit-Hook → SSE → zweiter Browser. Zehn Wiederholungen je Messpunkt, ein Worker, Windows-Host. Latenz beginnt unmittelbar vor der Mutation und endet beim beobachteten kanonischen Zustand im zweiten Browser. Reconnect beginnt mit dem erneuten Online-Schalten.
- SQLite-Stress: pro Wiederholung zwei verbundene Browser mit offenen SSE-Verbindungen, 40 parallele GETs und zehn parallele Preference-Writes. Zehn Wiederholungen, keine HTTP-5xx- oder Lock-Fehler.
- Startup: Produktionsbuild gegen denselben echten, deterministischen FastAPI-/SQLite-Fixture-Backendpfad. Zehn Cold- und zehn Warm-Samples. `main data ready` ist der vollständig empfangene Bootstrap; die SSE-Verbindung wird nicht als abgeschlossener Startup-Request gezählt.
- p95: Nearest-Rank. Bei zehn Samples ist p95 daher der höchste beobachtete Wert.
- Die vorherigen UI-Performancewerte stammen aus dem bestehenden deterministischen, gemockten Playwright-Referenztest. Sie sind nur mit dessen After-Lauf direkt vergleichbar.

## Before / After

| Messpunkt | Before | After | Einordnung |
|---|---:|---:|---|
| Referenz-E2E Initial Load | 1.811 ms | 619 ms | identischer gemockter Playwright-Test, finaler Build |
| Referenz-E2E Angebotsseite | 1.035 ms | 475 ms | identischer gemockter Playwright-Test, finaler Build |
| Referenz-E2E Favoritenmutation | 1.145 ms | 643 ms | identischer gemockter Playwright-Test, finaler Build |
| Konfigurierte Splash-Dauer | 1.050 ms | 260 ms | 800+250 ms → 160+100 ms |
| Account-Integritäts-Polling | 15 s | 120 s | Realtime primär über SSE; Polling nur Safety Net |
| Shared-List-Fallback-Polling | 1 s | 120 s | Realtime primär über SSE; Polling nur Safety Net |
| Live-Bootstrap vor Deployment | 339 ms / 141.069 B | nicht vergleichbar erhoben | Live-Produktionsdatenbestand ist auf diesem Branch noch nicht deployt |
| Lokaler Fixture-Bootstrap | nicht erhoben | Median 92,5 ms / 1.424 B | echte FastAPI-/SQLite-Antwort, kleiner deterministischer Datenbestand |
| Startup-API-Requests | nicht erhoben | 11 | keine doppelten Request-Keys in 10/10 Cold- und Warm-Läufen |
| Client-Hauptchunk | 297,61 kB / 94,08 kB gzip | 297,79 kB / 94,14 kB gzip | +0,18 kB / +0,06 kB gzip |
| Realtime-Einzellatenzen | nicht erhoben | siehe Tabelle unten | keine nachträglich konstruierten Before-Werte |

## Realtime-Latenzen

Alle Angaben in Millisekunden.

| Operation | Minimum | Median | p95 | Maximum |
|---|---:|---:|---:|---:|
| Favorit hinzufügen | 89 | 175 | 222 | 222 |
| Favorit entfernen | 93 | 179 | 221 | 221 |
| Alternativen | 62 | 100,5 | 172 | 172 |
| Produktfamilie | 44 | 76,5 | 120 | 120 |
| Shared List add | 120 | 141,5 | 279 | 279 |
| Quantity | 101 | 123 | 207 | 207 |
| Checked | 83 | 116 | 159 | 159 |
| Reconnect / Resume | 48 | 61,5 | 73 | 73 |

## Startup

Alle Zeitangaben in Millisekunden; je zehn Samples.

| Messpunkt | Minimum | Median | p95 | Maximum |
|---|---:|---:|---:|---:|
| Cold App Shell | 295 | 349 | 394 | 394 |
| Cold Main Data Ready | 338 | 412 | 497 | 497 |
| Cold Bootstrap Duration | 62 | 92,5 | 140 | 140 |
| Cold API Waterfall Span | 122 | 153 | 197 | 197 |
| Warm App Shell | 162 | 195,5 | 247 | 247 |
| Warm Main Data Ready | 240 | 280,5 | 356 | 356 |
| Warm Bootstrap Duration | 83 | 114,5 | 159 | 159 |
| Warm API Waterfall Span | 134 | 151,5 | 185 | 185 |

Bootstrap-Payload: konstant 1.424 Byte im deterministischen Fixture. Startup-Requests: konstant 11 Cold und 11 Warm. Doppelte Request-Keys: keine. Eine Messung mit produktionsgleichem Datenvolumen bleibt erst nach Deployment möglich; die lokale Payload darf nicht als Produktionsreduktion interpretiert werden.

Der abschließende reale Integrations-Smoke auf dem finalen Build lag innerhalb der oben dokumentierten Zehnerbandbreiten: Cold Shell 394 ms, Cold Main Data Ready 443 ms, Cold Bootstrap 96 ms; Warm Shell 151 ms, Warm Main Data Ready 188 ms, Warm Bootstrap 49 ms. Beide Starts erzeugten 11 Requests, 1.424 Byte Bootstrap-Payload und keine doppelten Request-Keys.

## SQLite- und Realtime-Härtung

- GET, HEAD, OPTIONS und SSE lösen keine `last_seen_at`-Updates, Client-Key-Migrationen oder Commits aus. Legacy-Clients werden bei Reads nur aufgelöst und erst bei echten Mutationen migriert.
- Account-Revisionszeilen werden bei der Migration für bestehende Nutzer vorbefüllt. PostgreSQL serialisiert parallele Revisionserhöhungen per Row-Lock; SQLite serialisiert über seinen Writer.
- Events entstehen einmalig aus Commit-Hooks. Frühere manuelle Doppel-Publishes und der alte 1-Sekunden-SSE-Pollingpfad sind entfernt.
- EventSource, Reconnect-Timer, Fallback-Intervalle sowie Focus-/Online-/Visibility-Listener werden beim Unmount abgeräumt. Late Safari/iOS-Callbacks werden über einen `stopped`-Guard neutralisiert.
- Der Zwei-Client-Stresstest bestand 10/10 Durchläufe ohne `database is locked`, HTTP 5xx oder verlorene abschließende Konvergenz.

## Admin Custom Push

- Versand an einen bestimmten Nutzer, alle aktiven Geräte oder genau eine zum Nutzer gehörende Subscription.
- Titel 1–80 Zeichen, Nachricht 1–300 Zeichen, interner Zielpfad maximal 300 Zeichen.
- Externe, protokollrelative, fragmentierte, Backslash-, Control-Character- und doppelt kodierte Traversal-Ziele werden abgewiesen.
- Same-Origin-Prüfung für Browser-POSTs; fremde Geräte-IDs werden abgewiesen.
- Ergebnis zeigt erfolgreich/fehlgeschlagen; Subscription-Zeitpunkt und letzter Fehler sind im Admin sichtbar.
- Audit Log enthält Nutzer, Ziel, Geräteauswahl und Zustellzahlen, aber bewusst keinen Nachrichteninhalt.
- Normale Shared-List-Mutationen führen keinen Web-Push-Transport synchron aus, sondern legen ihn in den bestehenden Hintergrund-Batch.

## CARTO

Die aktuelle Karte nutzt die öffentlichen CARTO-Voyager-Rastertiles ohne API-Key. `carto-API-Key.txt` bleibt ignoriert und wird weder gebündelt noch im Browser referenziert. Die sichtbare Kartenzeile ist keine entfernbare Demo-Markierung, sondern die lizenz-/nutzungsbedingte Attribution der Daten- und Kartenanbieter. `© OpenStreetMap contributors` und `© CARTO` bleiben sichtbar und verlinkt. Ein künftiger Wechsel auf authentifizierte CARTO-Dienste muss Tokens serverseitig bzw. als ausdrücklich public-scope Token verwalten und darf kein Secret in den Frontend-Build aufnehmen.

Referenzen: [CARTO API access tokens](https://docs.carto.com/carto-user-manual/developers/managing-credentials/api-access-tokens), [CARTO public applications](https://docs.carto.com/carto-for-developers/guides/build-a-public-application), [CARTO basemaps](https://docs.carto.com/carto-for-developers/carto-for-react/guides/basemaps), [OpenStreetMap copyright/attribution](https://www.openstreetmap.org/copyright).

## Rest-Risiken

- Die After-Messungen laufen lokal auf einem deterministischen kleinen Datenbestand. Live-TTFB, Mobilfunk, Produktions-Payload und echte Push-Providerlatenz sind damit nicht abgedeckt.
- SSE ist pro Prozess in-memory. Bei horizontaler Skalierung ist ein gemeinsamer Broker (zum Beispiel Redis/PostgreSQL NOTIFY) erforderlich.
- Realtime-Queues sind für die geplante 20-User-Beta ausreichend, aber noch nicht hart begrenzt oder koalesziert.
- Web Push bleibt von Browser-/OS-Zustellung, VAPID-Konfiguration und Nutzerberechtigungen abhängig; Unit-Tests ersetzen keinen Provider-Smoke-Test auf echten iOS-/Android-Geräten.
- Safari/iOS wird durch Playwright WebKit und defensive Lifecycle-Guards abgedeckt, nicht durch eine physische iPhone-PWA-Matrix.
- Der lokale Host hatte keinen laufenden Docker-/PostgreSQL-Dienst. Die verbindlichen Builds und PostgreSQL-Migrationstests werden deshalb durch die PR-CI entschieden.
- Der erste lokale Full-Playwright-Lauf bestand 107 Tests, übersprang 32 bewusst und fand sechs Fehler in zwei Ursachen. Nach deren Behebung waren die betroffenen Tests auf Chromium und WebKit Desktop/Mobile grün; ein zweiter Full-Lauf wurde nach einem Firefox-Startfehler durch einen nicht sicher zuordenbaren Altprozess abgebrochen. Der Preis-Scope-Test ist deshalb als `@critical` markiert und muss in der isolierten PR-CI auch unter Firefox grün werden.
