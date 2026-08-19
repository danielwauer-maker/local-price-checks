# Benchmarks

## Eingefrorene Referenz KW33/2026

| Händler | korrekt | Referenz | Quote |
|---|---:|---:|---:|
| REWE Dierdorf | 227 | 227 | 100 % |
| Netto | 359 | 361 | 99,45 % |
| ALDI SÜD | 170 | 174 | 97,70 % |
| **Gesamt** | **756** | **762** | **99,21 %** |

Die Gesamtfreigabe der bestehenden Engine basiert auf 99,21 %. Bekannte Goldfälle müssen bei jeder Parseränderung erhalten bleiben.

## Goldfälle

REWE: Freixenet Sekt 3,79 €, König Pilsener 10,99 €.

Netto: Dallmayr Prodomo 6,49 €, Zott Sahnejoghurt 0,44 €, Géramont 2,22 €, Haribo 0,79 €, Leberkäs-Brät 3,99 €, Old Amsterdam 2,29 €.

ALDI: NIVEA Deoroller 2,49 €, LEIBNIZ Butterkeks 1,19 €, Aperol 9,49 €.

## Regel für neue Märkte/Händler

Ein neuer Markt/Händler wird erst mit `benchmark_verified=true` für den Nutzervergleich freigegeben, wenn der vollständige Referenzbenchmark mindestens 99 % erreicht. REWE Straßenhaus bleibt deshalb zunächst nicht freigegeben, obwohl die Markt-ID 1940425 bereits im Seed enthalten ist.

## Reproduzierbare Phase-2-Golden-Fixtures

Die eingefrorenen Fixture-Dateien unter `tests/fixtures/golden/` bilden den kanonischen Adapter-Output vor der Persistenz ab. Der Runner wendet dieselben Local-/Online- und Qualitätsregeln wie der Import an und vergleicht Produktname, Preis, Packungsgröße, Grundpreis, Seite, Bildstatus und Referenzpreis. Varianten und Mehrfachfundstellen bleiben einzelne Fälle. REWE enthält zusätzlich die negativen Namensfragmente `Peanut`, `gegart` und `je St.`; Lidl enthält einen expliziten Online-only-Negativfall.

Ausgeführt am 20.08.2026:

| Händler | Precision | Recall | Provenance | Images | Package | Unit Price | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| REWE | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | PASS |
| Lidl | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | PASS |
| Netto Marken-Discount | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | PASS |
| ALDI SÜD | 100 % | 100 % | 100 % | 100 % | 100 % | 50 % | PASS |
| EDEKA | 100 % | 100 % | 100 % | 50 % | 100 % | 100 % | PASS |
| PENNY | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | PASS |
| ALDI NORD | 100 % | 100 % | 100 % | 50 % | 100 % | 100 % | PASS |

Precision/Recall messen die korrekte Annahme und Feldtreue der eingefrorenen Fälle. Die Coverage-Spalten messen dagegen, ob die jeweilige Quelle das Feld liefert; fehlende Bilder oder Grundpreise werden deshalb nicht als erfundene Werte schöngerechnet. Die Fixtures sind klein und deterministisch und ersetzen keine regelmäßigen Production-Smoke-Tests gegen veränderte Händlerseiten.
