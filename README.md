# Local Price Checks

Mobile-first Web-App für lokale Supermarkt-Preisvergleiche.

Local Price Checks verbindet persönliche Favoriten und die Einkaufsliste mit lokalen Wochenangeboten und soll beantworten: **Was sollte ich kaufen, wo ist es am günstigsten und lohnt sich ein zusätzlicher Markt?**

## MVP

- Favoriten
- Einkaufsliste mit Mengen
- aktuelle und kommende Angebote
- Barcode/GTIN per Handykamera oder Eingabe
- unbekannten Barcode einmalig einem Produkt zuordnen
- Hauptstandort via PLZ + Ort, ohne GPS-Freigabe
- Radius + favorisierte Märkte
- nur benchmark-freigegebene Märkte im Preisvergleich
- Sparplan mit Ein-Markt-/Mehrmarkt-Vergleich und lokaler Fahrtkostenschätzung
- Datenstatus je Markt
- automatische Wochen-Sammlung optional über Scheduler

Der stabile KW33-Referenzbenchmark für REWE Dierdorf, Netto und ALDI SÜD liegt bei **756/762 = 99,21 %**. EDEKA/Lidl bleiben vorerst außerhalb des MVP-Vergleichs. REWE Straßenhaus ist angelegt, aber noch nicht vollständig benchmark-freigegeben.

## Lokal auf Windows starten

```powershell
git clone https://github.com/danielwauer-maker/local-price-checks.git
cd local-price-checks
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Laptop: `http://localhost:8000`

Das Startskript zeigt zusätzlich die URL für ein Smartphone im selben WLAN an.

Für den echten Handykamera-Test über einen sicheren Browserkontext:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-https.ps1
```

Die vollständige Anleitung inklusive iPhone-/Android-Zertifikatsschritten steht in **`docs/LOCAL_TESTING.md`**.

## Manuell mit Docker

```bash
cp .env.example .env
docker compose up --build
```

SQLite bleibt der bequeme Standard. Die zentrale SQLAlchemy-URL wird über
`DATABASE_URL` gesetzt:

```bash
# SQLite
DATABASE_URL=sqlite:////app/data/local_price_checks.sqlite3

# lokales PostgreSQL (psycopg 3)
DATABASE_URL=postgresql+psycopg://lokero:lokero_dev_only@localhost:5432/lokero
AUTO_CREATE_SCHEMA=false
```

Das optionale PostgreSQL-Profil verändert den normalen SQLite-Compose-Start
nicht:

```bash
docker compose --profile postgres up -d postgres
export DATABASE_URL=postgresql+psycopg://lokero:lokero_dev_only@localhost:5432/lokero
export AUTO_CREATE_SCHEMA=false
python -m alembic upgrade head
```

Läuft auch das Backend in Compose, lautet der Hostname in `DATABASE_URL`
`postgres` statt `localhost`; danach `docker compose --profile postgres up
--build` verwenden.

Für eine spätere, geplante Datenübernahme (nicht auf Produktion ausführen, bevor
das Runbook vollständig abgearbeitet wurde):

```bash
python scripts/migrate_sqlite_to_postgres.py --sqlite-path /path/to/local_price_checks.sqlite3 --postgres-url "$DATABASE_URL" --dry-run
python scripts/migrate_sqlite_to_postgres.py --sqlite-path /path/to/local_price_checks.sqlite3 --postgres-url "$DATABASE_URL"
python scripts/verify_postgres_migration.py --sqlite-path /path/to/local_price_checks.sqlite3 --postgres-url "$DATABASE_URL"
```

Dry Run, Transfer und Verifikation führen automatisch denselben strikten
Schema-Preflight gegen die aktuelle SQLAlchemy-/Alembic-Baseline aus. Fehlende
oder zusätzliche Tabellen/Spalten sowie Drift bei Typen, Nullable, Primary/
Foreign Keys, Unique Constraints oder Indizes führen zu einem sicheren Abbruch
bzw. `RESULT: FAIL`; Legacy-Daten werden nicht stillschweigend ignoriert.

Alembic-Kommandos: `python -m alembic current`, `python -m alembic upgrade head`
und nach sorgfältigem Schemaabgleich einer bereits bestehenden SQLite-DB
`python -m alembic stamp 20260825_01`. Backup, Restore, Stamping, Cutover und
Rollback sind in **`docs/POSTGRESQL_MIGRATION_RUNBOOK.md`** beschrieben.

## Ohne Docker

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0
```

## Tests

```bash
python -m pytest -q
```

## Repository-Regeln

Nicht versioniert werden: produktive SQLite-Datenbanken, Prospekt-PDFs, Support-Exports, Cookies/Browserprofile, `.env`, lokale Zertifikate und Logs.

Weitere Details: `docs/MVP_SCOPE.md`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/LOCAL_TESTING.md`, `docs/POSTGRESQL_MIGRATION_RUNBOOK.md`.
