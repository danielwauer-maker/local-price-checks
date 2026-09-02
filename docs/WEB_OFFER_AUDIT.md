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

### EDEKA-Completeness und „Mehr laden“

Am 2. September 2026 wurde die sichtbare Marktseite für Fellenzer `071378`
erneut im echten Browser untersucht. Die initiale DOM-Antwort enthält bereits
alle 224 eindeutigen Angebots-IDs. Davon liegen 220 in acht
`<load-more data-max-items="8">`-Gruppen und vier im Highlight-Bereich:

| Kategorie | serverseitig gerendert | initial sichtbar |
|---|---:|---:|
| Obst & Gemüse | 23 | 8 |
| Molkerei & Käse | 34 | 8 |
| Grundnahrung | 47 | 8 |
| Tiefkühl | 11 | 8 |
| Fleisch & Wurst | 40 | 8 |
| Getränke | 32 | 8 |
| Knabbern & Naschen | 19 | 8 |
| Drogerie | 14 | 8 |

Weitere 156 Kategoriekarten tragen initial
`data-show-by-load-more="false"`. „Mehr laden“ ist damit kein Netzwerk-Cursor
und keine zusätzliche Server-Pagination, sondern ein Sichtbarkeits-Toggle auf
bereits vorhandenem HTML. Der Audit parst deshalb alle DOM-Karten unabhängig
von diesem Attribut. Für `071378` dient 224 als ausdrücklich marktspezifische
Regression-Referenz. Weniger Karten oder eine Abweichung zwischen eindeutigen
DOM-IDs und Parser-Ergebnis führen zu `partial`, niemals zu `success`.

#### Production-Fetch-Root-Cause (2. September 2026)

Der erste Production-Canary nach PR #160 fiel auf 10/224 zentrale Angebote
zurück. Der DOM-Parser war nicht die Ursache. Der HTTP-First-Pfad gab sich mit
einem fest codierten Chrome-User-Agent als Browser aus. In der lokalen und der
containerisierten Vergleichsumgebung lehnt Akamai genau diese Request-Variante
reproduzierbar ab, während der transparente GET vollständig funktioniert. Ob
die Zielumgebung zusätzlich IP-basiert eingeschränkt wird, kann erst der neue
Production-Canary mit den unten beschriebenen Diagnosefeldern entscheiden.

Die Diagnose wurde sowohl vom Host als auch aus dem Backend-Docker-Image gegen
die öffentliche Marktseite durchgeführt:

| Variante | Status | Body | Redirects / Finalhost | Ergebnis |
|---|---:|---:|---|---|
| Plain HTTPX GET | 200 | 1.276.824 Byte | 0 / `www.edeka.de` | vollständiges serverseitiges HTML |
| Transparenter `Spareno-Audit/1.0` GET | 200 | 1.276.824 Byte | 0 / `www.edeka.de` | vollständiges serverseitiges HTML |
| Übliche `Accept`-/`Accept-Language`-Header | 200 | 1.276.824 Byte | 0 / `www.edeka.de` | vollständig |
| Fest codierter Chrome-127-User-Agent | 403 | 402 Byte | 0 / `www.edeka.de` | `AkamaiGHost`, `Access Denied` |
| Plain HEAD | 404 | 0 Byte | 0 / `www.edeka.de` | nicht als Verfügbarkeitsprobe geeignet |
| Plain GET über IPv4 / IPv6 | 200 / 200 | jeweils 1.276.824 Byte | 0 / `www.edeka.de` | IP-Familie nicht ursächlich |

Die DNS-Kette war `www.edeka.de` → `www-v2.edeka.de.edgekey.net` →
`*.akamaiedge.net`; beobachtet wurden öffentliche A- und AAAA-Adressen. HTTPX
und das lokale Curl unterstützen in dieser Umgebung HTTP/1.1, über das der GET
vollständig funktioniert. Der initiale erfolgreiche Request benötigt keine
vorherigen Consent- oder Session-Cookies. `Set-Cookie` wird in der
Produktionsdiagnostik ausdrücklich nicht gespeichert.

HTML, JSON-LD, `application/json`, Preloads, DOM-Attribute und das öffentlich
geladene EDEKA-App-JavaScript wurden nach Hydration-State, CMS-Fragmenten und
Angebotsendpunkten untersucht. Die 224 Angebote liegen ausschließlich als
serverseitig gerenderte HTML-Karten vor. Im App-JavaScript wurden nur die
öffentlichen Suggestion-/Newsletter-Pfade gefunden; `offer-images.api.edeka`
ist ein reiner Bildhost. Ein alternativer strukturierter Dienst, dessen IDs
gegen alle 224 DOM-IDs verifiziert werden könnten, ist nicht nachgewiesen. Die
bereits bekannte `/eh/service/eh/offers`-Quelle bleibt mit 10 Angeboten reine
Diagnose-Evidenz und wird selbst bei einer größeren, aber nicht gegen DOM-IDs
bewiesenen Teilmenge niemals automatisch auf `complete` hochgestuft.

Der Collector verwendet deshalb für genau die zugelassenen öffentlichen
EDEKA-Marktseiten einen transparenten HTTP-GET, validiert Redirects vor dem
Folgerequest ausschließlich auf `https://edeka.de` beziehungsweise
`https://www.edeka.de` und protokolliert nur sichere Diagnosefelder. Ein
Browser bleibt kontrollierter Fallback; der Legacy-Feed bleibt immer
`partial`. Vor einer produktiven Aktivierung muss der vollständige 224er-Lauf
in der tatsächlichen Zielumgebung erneut als Canary reproduziert werden. Die
technische Erreichbarkeit einer öffentlichen Händlerseite ersetzt außerdem
keine rechtliche Prüfung der Nutzungsbedingungen und Datenrechte vor einem
regelmäßigen oder skalierten Produktionsabruf.

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
