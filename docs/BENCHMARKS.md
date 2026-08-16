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
