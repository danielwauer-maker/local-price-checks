# PostgreSQL migration runbook

Dieses Runbook bereitet einen späteren, bewusst freigegebenen Produktions-
Cutover vor. Der Readiness-Sprint selbst migriert keine Produktion. Alle
Befehle müssen zuerst mit einem aktuellen Produktions-Snapshot in einer
isolierten Staging-Umgebung erfolgreich geprobt werden.

## Konfiguration und Grundsätze

- SQLite: `sqlite:////absolute/path/local_price_checks.sqlite3`
- PostgreSQL: `postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE`
- Secrets gehören in die Deployment-Secret-Verwaltung, nie ins Repository.
- Auf PostgreSQL ist `AUTO_CREATE_SCHEMA=false`; Alembic besitzt das Schema.
- `Base.metadata.create_all()` bleibt übergangsweise nur für lokale/legacy
  SQLite-Starts aktiv. Es verändert keine vorhandenen Spalten und ersetzt
  Alembic nicht.
- Die Baseline `20260825_01` enthält alle 42 Tabellen aus
  `app.model_registry`. Neue Modelle müssen dort registriert sein und eine neue
  Alembic-Revision erhalten.

## 1. Preflight

1. Change-Freeze für Schema und schreibende Releases vereinbaren.
2. Genauen SQLite-Pfad, freien Speicher, PostgreSQL-Version und Zugang prüfen.
3. `PRAGMA integrity_check;` und `PRAGMA foreign_key_check;` auf einer Kopie
   ausführen. Ältere SQLite-Installationen haben Foreign Keys möglicherweise
   nicht erzwungen; ein späteres `PRAGMA foreign_keys=ON` repariert bereits
   vorhandene Orphans nicht. Alle Befunde müssen deshalb vor der Migration
   geklärt werden. Nur `integrity_check = ok` und null Zeilen aus
   `foreign_key_check` erlauben den nächsten Schritt.
4. Der Legacy-SQLite-Dry-Run führt den automatisierten, strikten Schema-
   Preflight gegen die
   vollständige SQLAlchemy-/Alembic-Baseline aus. Er vergleicht die exakte
   Tabellen- und Spaltenmenge, normalisierte Typen/Längen, Nullable, Primary und
   Foreign Keys, Unique Constraints sowie Indexsignaturen auf Quelle und Ziel.
   Fehlende oder zusätzliche Legacy-Strukturen sind ein Safety-Fehler und
   müssen vor dem Stamping bewusst migriert oder verworfen werden. Eine
   vorhandene SQLite-DB darf nur bei bestandenem Preflight gestempelt werden.
   Kein manuelles/blindes `alembic stamp` verwenden; das kontrollierte Script
   führt den Stamp ausschließlich auf einer geprüften Staging-Kopie aus.
5. Staging-Probe mit demselben Snapshot durchführen: Baseline, Dry Run,
   Transfer, Verifikation und API-Smoke-Tests.
6. Verantwortliche Person, Wartungsfenster, Abbruchzeitpunkt und Rollback-
   Entscheider festlegen.

### Kontrollierter Repair bekannter Offer-Orphans

Der Repair läuft ausschließlich auf einer ausdrücklich angegebenen SQLite-
Datei und ist standardmäßig ein Dry Run. Er gruppiert alle FK-Probleme und
bricht ohne Änderung ab, sobald ein Problem außerhalb der bekannten direkten
Offer-Beziehungen gefunden wird:

```bash
python scripts/repair_sqlite_foreign_keys.py /path/to/snapshot.sqlite3
```

Erst nach Prüfung der Ausgabe darf eine Snapshot-Kopie repariert werden. Mit
`--apply` wird vor der Transaktion automatisch ein timestampiertes Backup
erstellt; alternativ wird ein expliziter Backup-Pfad angegeben:

```bash
python scripts/repair_sqlite_foreign_keys.py /path/to/snapshot.sqlite3 \
  --apply \
  --backup-path /secure-backups/snapshot-before-fk-repair.sqlite3
```

Der Helper entfernt nur eindeutig verwaiste Zeilen aus
`offer_occurrences`, `offer_price_references` und `offer_provenance` (samt
deren abhängigen Review-Zeilen). Er rekonstruiert oder errät keine Parent-
Daten. Nach dem Apply müssen die ausgegebenen Prüfungen erneut
`integrity_check = ok` und `foreign_key_check = 0` zeigen. Das Original der
Produktionsdaten wird weder beim App-Start noch durch den Migrationsprozess
automatisch bereinigt.

## 2. Maintenance Window und Schreibstopp

1. Wartungsseite aktivieren oder alle schreibenden API-/Worker-/Scheduler-
   Instanzen stoppen. `SCHEDULER_ENABLED=false` allein genügt nicht.
2. Sicherstellen, dass keine offenen Writer mehr existieren.
3. Erst nach dem bestätigten Schreibstopp den finalen SQLite-Snapshot erzeugen.
4. Bis zur Cutover-Entscheidung SQLite nicht wieder schreibbar starten.

## 3. SQLite-Backup

Der Helper verwendet die SQLite-Backup-API, überschreibt keine Datei und prüft
die Sicherung mit `integrity_check`:

```bash
python scripts/backup_database.py sqlite \
  --source /srv/lokero/data/local_price_checks.sqlite3 \
  --output /secure-backups/lokero-pre-pg-YYYYMMDD-HHMM.sqlite3
sha256sum /secure-backups/lokero-pre-pg-YYYYMMDD-HHMM.sqlite3 > /secure-backups/lokero-pre-pg-YYYYMMDD-HHMM.sha256
```

Original, Backup und Prüfsumme getrennt aufbewahren. WAL-/SHM-Dateien niemals
isoliert kopieren; der Helper erzeugt ein konsistentes Einzeldatei-Backup.

## 4. PostgreSQL-Backup und leeres Ziel

Wenn die Zielinstanz bereits existiert, vor Änderungen sichern:

```bash
python scripts/backup_database.py pg-dump \
  --postgres-url "$DATABASE_URL" \
  --output /secure-backups/lokero-postgres-before-YYYYMMDD-HHMM.dump
```

Für die eigentliche Migration eine neue, leere Datenbank bevorzugen. Der
Migration-CLI verweigert standardmäßig jedes Ziel mit Anwendungsdaten.
`--allow-nonempty` ist nur für einen separat geprüften Sonderfall vorgesehen;
es überschreibt keine Zeilen und Constraint-Konflikte brechen die gesamte
Transaktion ab.

## 5. Schema erstellen

### A) Neue Datenbank

```bash
export DATABASE_URL='postgresql+psycopg://...'
export AUTO_CREATE_SCHEMA=false
python -m alembic upgrade head
python -m alembic current
```

### B) Historische SQLite ohne Alembic-Version

Die App, Worker und Scheduler müssen gestoppt sein. Zuerst ausschließlich den
read-only Dry Run ausführen:

```bash
python scripts/prepare_existing_sqlite_for_alembic.py \
  --sqlite-path /srv/lokero/data/local_price_checks.sqlite3
```

Nur bei `integrity_check = ok`, null FK-Befunden und exakter semantischer
Übereinstimmung mit `20260825_01` darf Apply folgen:

```bash
python scripts/prepare_existing_sqlite_for_alembic.py \
  --sqlite-path /srv/lokero/data/local_price_checks.sqlite3 \
  --apply \
  --backup-path /secure-backups/lokero-pre-alembic-YYYYMMDD-HHMM.sqlite3
```

Das Script überschreibt kein Backup. Es erstellt eine konsistente Sicherung,
prüft Quelle und Backup erneut und arbeitet anschließend ausschließlich auf
einer Staging-Kopie. Nur wenn Stamp `20260825_01`, Upgrade auf `20260825_02`,
`integrity_check`, `foreign_key_check` und aktueller Schemaabgleich erfolgreich
sind, ersetzt die Staging-Datei atomar die Quelle. Bei Drift, beschädigter DB,
unbekannten FK-Problemen, unbekannter Revision oder aktivem WAL bricht es ohne
Änderung der Quelle ab. Bereits auf `20260825_02` befindliche Datenbanken werden
idempotent als aktuell gemeldet.

Nicht `upgrade` auf eine volle, ungestempelte Baseline-Datenbank anwenden: die
Baseline versucht Tabellen zu erzeugen und muss dann fehlschlagen. Stamping ist
kein Reparaturwerkzeug und darf außerhalb des geprüften Scripts nicht erfolgen.

## 6. Dry Run und Datenmigration

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-path /secure-backups/lokero-pre-pg-YYYYMMDD-HHMM.sqlite3 \
  --postgres-url "$DATABASE_URL" --dry-run

python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-path /secure-backups/lokero-pre-pg-YYYYMMDD-HHMM.sqlite3 \
  --postgres-url "$DATABASE_URL"
```

Der Kopierer verlangt den exakten aktuellen Baseline-Schemaabgleich auf Quelle
und Ziel; zusätzliche Legacy-Tabellen oder -Spalten werden nie ignoriert. Dry
Run und echter Transfer nutzen denselben Preflight. Danach kopiert er in
Foreign-Key-Reihenfolge, erhält explizite Primary Keys und NULLs, arbeitet in
einer PostgreSQL-Transaktion und setzt anschließend alle erkannten Serial-
Sequences auf `MAX(id)`. Bei einem Fehler wird die Zieltransaktion
zurückgerollt; die SQLite-Quelle wird read-only verwendet und nie gelöscht.

## 7. Verifikation

```bash
python scripts/verify_postgres_migration.py \
  --sqlite-path /secure-backups/lokero-pre-pg-YYYYMMDD-HHMM.sqlite3 \
  --postgres-url "$DATABASE_URL"
```

Nur `RESULT: PASS` ist akzeptabel. Die Verifikation wiederholt zunächst den
strikten Schemaabgleich auf SQLite und PostgreSQL und meldet jede Drift als
`schema:source` oder `schema:target` FAIL. Danach werden Tabellen- und Row-
Counts, Primary-Key-Werte, Max-IDs, Sequence-Stände, sämtliche modellierten
Foreign Keys sowie explizit geprüft:

- `UserProfile -> UserClient`
- `AccountIdentity -> UserProfile`
- `AccountClientLink -> AccountIdentity/UserClient`
- Favoriten -> Profil/Markt/Produkt
- Einkaufsliste -> Profil/Produkt

Zusätzlich stichprobenartig bekannte anonyme und account-verknüpfte Clients mit
ihren exakten IDs, PLZ/Radius, Favoriten und Shopping-Items prüfen. Kein
zusätzliches `UserProfile` darf entstanden sein.

## 8. Cutover und Smoke Tests

1. Erst nach vollständigem PASS das Deployment-Secret `DATABASE_URL` auf die
   PostgreSQL-URL setzen; `AUTO_CREATE_SCHEMA=false` bestätigen.
2. Genau eine App-Instanz ohne Scheduler starten und `/health` prüfen.
3. Smoke-Tests: anonymer bestehender Client, neuer anonymer Client,
   Account-Linking über zwei Geräte, Profil/PLZ/Radius, Markt- und Produkt-
   Favoriten, Einkaufsliste, Lesen aktueller Angebote und Admin-Read-only-
   Ansichten.
4. Einen neuen Testdatensatz anlegen und kontrollieren, dass dessen ID größer
   als die migrierte Max-ID ist.
5. Danach übrige Instanzen und zuletzt Scheduler/Collector aktivieren.

## 9. Rollback-Kriterien

Sofort zurückrollen bei FAIL der Verifikation, fehlenden/anders zugeordneten
Nutzerdaten, Constraint-/Sequence-Fehlern, nicht erklärbaren API-Fehlern oder
überschrittenem Wartungsfenster.

Solange PostgreSQL noch keine neuen Produktionsschreibzugriffe angenommen hat:

1. PostgreSQL-App stoppen.
2. `DATABASE_URL` auf den unveränderten finalen SQLite-Snapshot zurücksetzen.
3. SQLite-App und anschließend Worker kontrolliert starten.
4. Smoke-Tests durchführen und Vorfall dokumentieren.

Nach neuen Schreibzugriffen auf PostgreSQL ist ein einfacher Rückwechsel zur
alten SQLite-Datei **kein verlustfreier Rollback**. Dann würden neue/aktualisierte
Profile, Favoriten und Listen fehlen. In diesem Fall Schreibzugriffe erneut
stoppen und entweder PostgreSQL vorwärts reparieren oder einen separat
entwickelten, geprüften Reverse-Transfer/Reconciliation-Plan ausführen. Ohne
einen solchen Plan nicht auf SQLite zurückschalten.

Ein PostgreSQL-Restore in eine leere, isolierte Datenbank erfolgt zum Beispiel:

```bash
python scripts/backup_database.py pg-restore \
  --postgres-url 'postgresql+psycopg://.../empty_restore_target' \
  --input /secure-backups/lokero-postgres-before-YYYYMMDD-HHMM.dump
```

## 10. Nacharbeiten

1. Direkt nach stabilem Cutover `pg_dump` erstellen, verschlüsselt offsite
   ablegen und einen isolierten Restore-Test durchführen.
2. Monitoring für DB-Verbindungen, Fehler, Storage und Backup-Jobs aktivieren.
3. SQLite-Original und finalen Snapshot mindestens über das vereinbarte
   Rollback-/Release-Fenster unverändert und read-only behalten.
4. Die alte SQLite-Datei erst archivieren, wenn PostgreSQL stabil ist, Backups
   wiederholt erfolgreich waren, ein Restore getestet wurde und Product/Tech
   den Ablauf formell freigegeben haben. Archivieren bedeutet nicht löschen;
   Löschung folgt einer separaten Aufbewahrungsrichtlinie.

## Portabilitätsaudit

Der Anwendungscode verwendet SQLAlchemy-Ausdrücke für Queries, `ILIKE`,
Booleans, Datum/Zeit und Schemazugriff. Die verbleibenden `PRAGMA`-Anweisungen
sind bewusst ausschließlich am SQLite-Dialekt registrierte Connection-Härtung
beziehungsweise Backup-Integritätsprüfungen. `check_same_thread` wird ebenfalls
nur für SQLite gesetzt. Es gibt im Laufzeit-/Migrationspfad kein `INSERT OR
REPLACE`, `sqlite_master` oder SQLite-spezifisches Upsert. Datei-Pfade werden nur
für ausdrücklich angegebene SQLite-Quellen verwendet.
