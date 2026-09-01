# Web-Angebots-Audit

Stand: 1. September 2026. Dieser Pfad dient ausschließlich der technischen und
fachlichen Prüfung offizieller Händler-Webangebote. Er schreibt weder in
`offers` noch in `master_products`, startet keinen produktiven Import und
verändert die bestehenden REWE-/Prospekt-Collector nicht.

## Bedienung und Sicherheitsgrenzen

Im Adminbereich steht unter **Prospekt-QA → Web-Angebots-Audit** die Auswahl von
Händler, Markt, aktueller oder nächster Woche bereit. Der Lauf verwendet nur
die am Markt gespeicherte URL. Zulässig sind ausschließlich HTTPS-Hosts des
jeweiligen Händlers; beliebige URLs und externe Redirect-Ziele werden
abgewiesen. CAPTCHAs und Zugriffssperren werden als `captcha` beziehungsweise
`blocked` gemeldet und niemals umgangen.

Die fünf neuen Produktionsflags sind standardmäßig `false`:

```text
WEB_COLLECTOR_NETTO
WEB_COLLECTOR_EDEKA
WEB_COLLECTOR_PENNY
WEB_COLLECTOR_ALDI_SUED
WEB_COLLECTOR_NORMA
```

Ein explizit ausgelöster Admin-Audit bleibt bei deaktiviertem Flag möglich. Das
ist Absicht: So können Daten geprüft werden, ohne sie produktiv freizuschalten.
REWE bleibt unverändert.

Jeder Lauf legt einen begrenzten Snapshot in
`DATA_DIR/diagnostics/web_offer_audit/<store-id>/` ab. Das Manifest enthält
Quellmetadaten, Offer-IDs, Counts, Hash, Netzwerk-URLs, Console-Fehler und
fehlgeschlagene Requests. Bei Fehlern kommen ein auf 2 MB begrenzter
HTML-/JSON-Snapshot und – sofern der Browser ihn erzeugen konnte – ein auf 5 MB
begrenzter Screenshot hinzu. Pro Markt bleiben maximal 20 Läufe erhalten.

## Extraktionswege

| Händler | Primärer Pfad | Marktparameter | Vollständigkeitsmechanik | Aktuell/Nächste Woche |
|---|---|---|---|---|
| REWE | bestehender strukturierter REWE-Parser | Markt-ID/Angebots-URL | bestehender Browser-Fallback | bestehendes Verhalten unverändert |
| Netto | bestehender strukturierter Filialkarten-Parser | `storeid`/persistierter Filialkontext | Browser lädt und scrollt die Filialseite; Duplikate per Händler-ID bzw. normalisiertem Schlüssel | Quellzeitraum der Filialseite |
| EDEKA | semantisches serverseitiges HTML | sechsstellige Markt-ID im URL-Pfad | alle Karten liegen im HTML; „Mehr laden“ ist nur clientseitige Darstellung | Gültigkeitsdaten aus Seite/Karte |
| PENNY | offizielles REST `/.rest/offers/by-category/<jahr>-<kw>/<kategorie>` | Marktseite plus regionale Highlights | alle beobachteten Kategorien, maximal 40 Responses; permanente Preissenkungen werden ausgeschlossen | ISO-Woche wird strikt getrennt |
| ALDI SÜD | offizielles `api.aldi-sued.de/v3/product-search` | `servicePoint` muss exakt der gespeicherten Filial-ID entsprechen | `offset`/`limit` bis `meta.pagination.totalCount`, maximal 40 Seiten, 3 Retries mit Pacing | nur Daten des erkannten Wochenendpoints; weitere Wochen-Audits nötig |
| NORMA | semantisches serverseitiges HTML | auf der Angebotsseite kein belastbarer Filialparameter nachgewiesen | Datumslinks (Mo/Mi/Fr) werden aus der Navigation ermittelt, nach ISO-Woche gruppiert und auf 7 Seiten begrenzt | nächste Woche ausschließlich über dynamisch gefundenen Link |

Private URLs werden nicht blind aus UI-Routen abgeleitet. Die PENNY- und
ALDI-Endpunkte wurden in echten Browser-Netzwerkantworten entdeckt. Es waren
keine API-Schlüssel nötig. EDEKA und NORMA liefern verwertbares HTML; OCR ist
nicht erforderlich.

## Reale technische Inventur

Die folgenden Werte stammen aus echten Händlerseiten am 1. September 2026 und
sind keine Test-Fixtures.

| Händler / Marktvergleich | Ergebnis |
|---|---|
| EDEKA Puderbach `071378` | 224 eindeutige Karten, 224 strukturell gültige Produktbilder, Zeitraum 31.08.–05.09.2026 |
| EDEKA Puderbach ↔ Köln `070287` | 224/223, 223 gemeinsam, Jaccard 0,9955, keine Preis- oder Gültigkeitsabweichung |
| EDEKA Puderbach ↔ Berlin `801604` | 224/252, 4 gemeinsam, Jaccard 0,0085 |
| EDEKA Puderbach ↔ München `030132` | 224/209, 4 gemeinsam, Jaccard 0,0093 |
| Netto Dierdorf `6822` ↔ Oberhonnefeld `2648` | 197/197, vollständig identisch |
| Netto Dierdorf ↔ Berlin `7770` | 197/197, 161 gemeinsam, Jaccard 0,6910, eine Preisabweichung |
| Netto Dierdorf ↔ München City `8441` | 197/96, 77 gemeinsam, Jaccard 0,3565 |
| PENNY Berlin `4030882` ↔ Berlin `531493` | vollständige beobachtete Sets identisch (292/292) |
| PENNY Berlin ↔ München `830784` | 292/291, 285 gemeinsam, Jaccard 0,9564 |
| PENNY Berlin ↔ Hessen `320590` | 292/290, 285 gemeinsam, Jaccard 0,9596 |
| ALDI SÜD Mülheim `B384` | offizieller Wochenendpunkt meldete 97 Produkte; vier Markt-Teaser enthielten jeweils dieselben 41 Angebote |
| NORMA Seite ab 31.08.2026 | 130 Produktkarten, 129 mit explizitem Preis, 130 mit Bild, eine reine Prozentaktion ohne Einzelpreis |

Interpretation: EDEKA ist klar regional und folgt zusätzlich den
Regionalgesellschaften. Netto ist stark regional; City-Filialen können ein
deutlich kleineres Sortiment haben. PENNY ist überwiegend national, besitzt
aber echte regionale Zusatzangebote. ALDI SÜD bleibt nach dem Teaservergleich
regional fachlich **unbekannt**, weil erst vollständige paginierte Läufe je
`servicePoint` diese Frage beantworten. Für NORMA wurde auf der Angebotsseite
kein reproduzierbarer filialbezogener Angebotsdatensatz gefunden; auch dort ist
die Regionalität **unbekannt**.

## Web ↔ Prospekt

Der Vergleich wird pro Markt und Lauf gespeichert und zeigt
`prospect_count`, `web_count`, `matched`, `web_only`, `prospect_only`,
Preis-/Mengenübereinstimmungen und Bildverfügbarkeit. Die Reihenfolge ist:

1. EAN, sofern sie im Produktstamm existiert,
2. normalisierte Marke + Produkt + Packungsgröße,
3. eindeutige bestehende Produktfamilie,
4. Fuzzy-Ähnlichkeit ausschließlich als gezählter Audit-Hinweis.

Externe Produkt-IDs werden in den Web-Snapshots vollständig gespeichert. Der
bestehende Prospekt-Datenbestand besitzt dafür noch kein symmetrisches Feld;
deshalb kann diese erste Priorität erst greifen, sobald der Prospektparser die
Händler-ID ebenfalls als Provenance liefert. Fuzzy-Treffer führen niemals zu
einer produktiven Zusammenführung.

Ein belastbarer numerischer Web-vs-Prospekt-Benchmark setzt passende aktuelle
Prospektarchive für denselben Markt und Zeitraum voraus. Fehlen sie, zeigt der
Audit offen `prospect_count = 0`; daraus wird keine Vollständigkeit erfunden.

## Produktionsentscheidung

| Händler | Klasse | Begründung / nächster Schritt |
|---|---|---|
| Netto | B | Filialdaten funktionieren, regionale Streuung und vorausgewählter Browserkontext brauchen weitere Wiederholungsläufe. |
| EDEKA | B | Sehr vollständige, marktspezifische HTML-Oberfläche; vor Aktivierung Browser-/CDN-Stabilität in der Zielumgebung als Canary prüfen. |
| PENNY | B | Stabile strukturierte API und getrennte Wochen; regionale Highlights und Marktauswahl weiter benchmarken. |
| ALDI SÜD | B | API/Pagination sind sauber, aber vollständige Mehrmarkt-Audits je `servicePoint` fehlen noch. |
| NORMA | C | Strukturierte HTML-Karten funktionieren; ein belastbarer filialbezogener Scope fehlt. |

Aktuell wird kein Händler automatisch aktiviert. Der sinnvollste nächste
Canary ist EDEKA mit wenigen fest definierten Märkten aus mehr als einer
Regionalgesellschaft. Erst nach wiederholtem Count-/Preis-/Zeitraumvergleich
gegen die zugehörigen Prospektarchive sollte das Flag produktiv gesetzt werden.
