# EDEKA Fellenzer Realtest

## Ziel

Dieser Realtest bringt genau einen zweiten Händler neben dem bestehenden REWE-Produktionsmarkt in den kontrollierten Spareno-End-to-End-Fluss:

- EDEKA Fellenzer
- Urbacher Straße 35
- 56305 Puderbach
- EDEKA Markt-ID `071378`

Kein V6-Import, kein Massenrollout, keine automatische Veröffentlichung.

## Routing / Optimierer

Der Optimierer verwendet für 1 bis 3 tatsächlich genutzte Märkte jetzt eine Straßen-Distanzmatrix über OSRM und prüft lokal alle möglichen Markt-Reihenfolgen für eine geschlossene Rundfahrt:

`Nutzerstandort -> Markt/ Märkte -> Nutzerstandort`

Konfiguration:

- `ROUTING_BASE_URL` (Default: `https://router.project-osrm.org`)
- `ROUTING_TIMEOUT_SECONDS`
- `ROUTE_DISTANCE_FACTOR` bleibt ausschließlich als Fallback-Faktor erhalten
- `DRIVING_COST_PER_KM` bleibt die Kostenbasis pro gefahrenem Kilometer

Wenn OSRM nicht erreichbar ist oder keine vollständige Distanzmatrix liefert, fällt die Berechnung kontrolliert auf Haversine-Luftlinie * `ROUTE_DISTANCE_FACTOR` zurück. Der Optimierer crasht dabei nicht.

## EDEKA Live-Quelle

Der normale EDEKA-Realtest läuft über den zentralen `edeka_live_collector` (Central + lokale Fellenzer-Ergänzung), nicht über Demo- oder Fixture-Daten.

Für Fellenzer gelten zusätzliche Sicherheitsprüfungen:

- Markt-ID der Quelle muss `071378` sein.
- Angebote müssen an denselben Store und Händler `EDEKA` gebunden sein.
- Angebote müssen einen aktuellen Gültigkeitszeitraum besitzen und den heutigen Stichtag einschließen.
- Die lokale Ergänzungsquelle muss erfolgreich sein.
- Die Zentralquelle muss vollständig sein.

Der historische Fellenzer-Referenzwert von 224 zentralen Angeboten ist kein unveränderlicher Wochenwert mehr. Entscheidend ist zuerst die vollständige DOM-/Kategorie-/ID-Abdeckung. Zusätzlich bleibt ein Collapse-Gate aktiv: mindestens 95 % des historischen Referenzwerts (= 213 Angebote) müssen erreicht werden. Dadurch ist ein normaler Wochenwechsel wie aktuell 223 statt 224 erlaubt, ein deutlicher Einbruch bleibt blockiert.

## Manueller Admin-Ablauf

1. Adminbackend öffnen und zu `Collector Support` (`/admin/collector`) gehen.
2. Den kanonischen Markt `EDEKA Fellenzer` / `071378` auswählen.
3. Sicherstellen, dass der Markt aktiv, aber noch nicht veröffentlicht (`benchmark_verified=false`) ist.
4. Den einzelnen Markt-Run starten.
5. Bei einem unveröffentlichten Markt startet dadurch automatisch der Test-Scrape-Lifecycle (`begin_test_scrape`).
6. Warten, bis der Run abgeschlossen ist.
7. CollectionRun und Quality-Snapshot kontrollieren. Der Test-Scrape wird nur bei erfolgreichem Run mit `complete_test_scrape` abgeschlossen; Fehler landen über `fail_test_scrape` im sichtbaren Status.
8. Erst wenn das Quality Gate die Freigabe erlaubt, den Markt explizit über den Release-Button freigeben. Der Release-Endpunkt ruft `publish_store` auf; ein bloßer Scrape veröffentlicht den Markt nicht.

## Was vor der Freigabe geprüft werden soll

Für den ersten manuellen Realtest insbesondere:

- Markt-ID `071378`
- Angebotszeitraum der aktuellen Woche
- Anzahl der importierten Angebote plausibel
- keine leeren Produktnamen
- Preise plausibel
- Bilder vorhanden, soweit die Quelle sie liefert
- Kategorien plausibel
- keine offensichtlich falschen Duplikate/Varianten-Merges
- keine Angebote eines anderen Markts
- Quality Gate ohne Blocker

## Prüfung in der normalen App

Nach expliziter Freigabe:

1. App neu laden.
2. Unter Märkte prüfen, dass REWE und EDEKA beide sichtbar sind.
3. EDEKA als Markt auswählen/favorisieren.
4. Angebotsseite auf EDEKA-Angebote prüfen.
5. Stichproben manuell gegen die aktuelle EDEKA-Quelle prüfen (Name, Preis, Bild, Laufzeit).
6. REWE + EDEKA gleichzeitig auswählen.
7. Mehrere Artikel auf die Einkaufsliste setzen, idealerweise mit Preisüberschneidungen zwischen beiden Märkten.
8. Optimierung aktivieren und Ergebnis prüfen.

## Zwei-Markt-Test

Der relevante Test ist nicht nur "welcher Artikel ist wo am billigsten", sondern:

`Warenkorbpreis + Rundfahrtkosten`

Beispiel:

- REWE Produkt A: 2,49 EUR
- EDEKA Produkt A: 1,79 EUR

Die 0,70 EUR Warenersparnis rechtfertigt einen zweiten Markt nur, wenn die zusätzliche Straßenroute inklusive `DRIVING_COST_PER_KM` den Gesamtpreis trotzdem senkt.

Die App zeigt bereits Fahrstrecke und Fahrtkosten im Optimierer an. Die berechnete Strecke stammt primär aus dem Straßenrouting; nur bei Routing-Ausfall wird intern auf die Schätzung zurückgefallen.

## Optimierer einschalten

Die Feature-Flags `optimization` und `savings` sind standardmäßig deaktiviert. Für den kontrollierten Realtest müssen beide explizit aktiviert werden. Dies ändert keine Marktdaten und veröffentlicht keine zusätzlichen Märkte.

## Problem-Diagnose

Bei einem EDEKA-Fehler zuerst prüfen:

- `/admin/collector`
- letzten `CollectionRun`
- Quality-Snapshot des Runs
- Run-Message / technischer Fehler
- `central_completeness_status`
- `market_page_id`
- `source_breakdown.local_status`
- Angebotsanzahl und Gültigkeitszeitraum

Typische harte Blocker sind bewusst:

- falsche oder fehlende Markt-ID
- Central-Completeness nicht `complete`
- Fellenzer Local-Supplement nicht `success`
- Angebote außerhalb des aktuellen Zeitraums
- Angebote mit falscher Store-/Händlerbindung
- Quality Gate nicht bestanden

## Außerhalb dieses Sprints

Bewusst nicht enthalten:

- V6-Datenimport
- deutschlandweiter Massenrollout
- automatische Freigabe vieler Märkte
- autonomous Agent-Rollout
- weitere Händlerketten
- großflächiges Admin-Redesign
