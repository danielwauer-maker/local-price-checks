# Architektur

## Laufzeit

FastAPI + Jinja2 + SQLAlchemy + SQLite für den lokalen MVP. Die Anwendung ist Docker-fähig und die Datenbank liegt in einem persistenten Volume.

## Datenfluss

Offizielle Händlerquelle / Prospekt -> Collector/Parser -> Qualitätsgate -> normalisierte Produkte/Angebote -> Nutzerfilter (Standort, Radius, Markt-Favoriten) -> Produktfavoriten/Einkaufsliste -> Sparplan.

## Datenschutz V1

Keine Browser-Geolocation. Gespeichert werden lediglich PLZ, Ort, daraus aufgelöste ungefähre Koordinaten, Radius und ausgewählte Märkte.

## Datenbankentwicklung

SQLite bleibt für lokale Entwicklung und ersten kleinen Webbetrieb. Bei Mehrbenutzer-/Haushaltsbetrieb ist PostgreSQL als nächster Schritt vorgesehen.
