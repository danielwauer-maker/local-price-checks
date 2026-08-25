# Sprint C: kontrollierter Produktions-Rollout auf SQLite

Dieses Runbook ist eine Befehlsvorlage für einen **manuell freigegebenen**
Produktions-Rollout. Es wurde nicht gegen den Produktionsserver ausgeführt.
Es verändert weder automatisch Produktionsdaten noch Container. Jeder Block
wird vom Operator einzeln ausgeführt und anhand der genannten Erwartung
abgenommen.

Sprint C wurde mit `1584fe8067bae7575cd49fccf825fb8cc7b30e76`
(PR #93) gemergt. Der tatsächlich freigegebene `TARGET_SHA` muss zusätzlich
die Rollout-Härtung enthalten. Niemals allein wegen dieses Dokuments deployen.

## 1. Voraussetzungen

- Wartungsfenster, Operator, Freigeber und Rollback-Entscheider sind benannt.
- Alle API-, Scheduler-, Collector- und sonstigen SQLite-Writer sind bekannt.
- Benötigt werden `git`, Docker Compose v2, Python 3.12 mit den Repository-
  Requirements, `sqlite3`, `curl`, `jq`, `sha256sum`, `stat`, `df` und `lsof`
  (oder ein gleichwertiger Open-File-Check).
- Der Operator setzt die folgenden Werte bewusst. Kein Beispielpfad darf
  ungeprüft übernommen werden:

```bash
set -euo pipefail
export REPO_DIR='/ABSOLUTER/PFAD/ZUM/PRODUKTIONS-REPOSITORY'
export RELEASE_DIR='/ABSOLUTER/PFAD/ZU/EINEM/LEEREN/RELEASE-WORKTREE'
export DB_PATH='/ABSOLUTER/HOST-PFAD/local_price_checks.sqlite3'
export BACKUP_DIR='/ABSOLUTER/PFAD/ZU/GESCHUETZTEN/BACKUPS'
export EVIDENCE_DIR='/ABSOLUTER/PFAD/ZUM/ROLLOUT-PROTOKOLL'
export BASE_URL='https://PRODUKTIONS-HOST'
export PYTHON_BIN='/ABSOLUTER/PFAD/ZUM/python'
export PYTHONPATH="$RELEASE_DIR"
export TARGET_SHA='<FREIGEGEBENER-MAIN-SHA-NACH-MERGE-DER-ROLLOUT-HAERTUNG>'
export SPRINT_C_SHA='1584fe8067bae7575cd49fccf825fb8cc7b30e76'
export ROLLOUT_ID="$(date -u +%Y%m%dT%H%M%SZ)"
export BACKUP_PATH="$BACKUP_DIR/local_price_checks.pre-sprint-c.$ROLLOUT_ID.sqlite3"
mkdir -p "$EVIDENCE_DIR"
cd "$REPO_DIR"
```

`DB_PATH` muss anhand von `.env` und der aufgelösten Compose-Konfiguration
bestätigt werden. Im Repository bindet der Service `app` `./data` nach
`/app/data`; `.env.example` nennt im Container
`/app/data/local_price_checks.sqlite3`. Produktion kann davon abweichen:

```bash
docker compose config > "$EVIDENCE_DIR/compose.before.yml"
docker compose config --services
grep -nE 'DATABASE_URL|source:|target:' "$EVIDENCE_DIR/compose.before.yml"
readlink -f "$DB_PATH"
test -f "$DB_PATH"
```

Erwartete Services sind `app`, `frontend`, `gateway`; `postgres` gehört nur
zum optionalen Profil. Bei einer Abweichung **STOP** und Pfade/Projektdateien
klären.

## 2. Production preflight

Zielcode separat bereitstellen, ohne den laufenden Checkout umzuschalten:

```bash
cd "$REPO_DIR"
test -z "$(git status --porcelain)"
git fetch origin main
test "$(git rev-parse origin/main)" = "$TARGET_SHA"
git merge-base --is-ancestor "$SPRINT_C_SHA" "$TARGET_SHA"
git show "$TARGET_SHA:migrations/versions/20260825_02_product_category_hierarchy.py" | grep 'down_revision.*20260825_01'
test ! -e "$RELEASE_DIR"
git worktree add --detach "$RELEASE_DIR" "$TARGET_SHA"
cd "$RELEASE_DIR"
"$PYTHON_BIN" -m alembic heads
"$PYTHON_BIN" -m alembic history
```

Erwartung: genau ein Head `20260825_02`; die Kette ist
`20260825_01 -> 20260825_02`. Revision `20260825_02` ergänzt ausschließlich
die nullable Spalte `product_categories.parent_id`, deren Self-FK und Index.
Sie löscht keine Produkte/Kategorien und schreibt weder Category-IDs noch
`product_admin_data` um.

Ist-Zustand beweissicher erfassen:

```bash
cd "$REPO_DIR"
export OLD_GIT_SHA="$(git rev-parse HEAD)"
printf '%s\n' "$OLD_GIT_SHA" > "$EVIDENCE_DIR/old-git-sha.txt"
docker compose images > "$EVIDENCE_DIR/images.before.txt"
sha256sum "$DB_PATH" | tee "$EVIDENCE_DIR/db.sha256.before.txt"
stat -c 'path=%n size=%s uid=%u gid=%g mode=%a mtime=%y device=%d inode=%i' "$DB_PATH" \
  | tee "$EVIDENCE_DIR/db.stat.before.txt"
stat -c '%u:%g:%a' "$DB_PATH" > "$EVIDENCE_DIR/db.owner-group-mode.before.txt"
for sidecar in "$DB_PATH-wal" "$DB_PATH-shm"; do
  if test -e "$sidecar"; then stat -c 'path=%n size=%s uid=%u gid=%g mode=%a mtime=%y' "$sidecar"; else echo "absent: $sidecar"; fi
done | tee "$EVIDENCE_DIR/db.sidecars.before.txt"
df -Pk "$DB_PATH" "$BACKUP_DIR" | tee "$EVIDENCE_DIR/disk.before.txt"
```

Freier Speicher ist konservativ zu planen: Liegen DB, Backup und Staging auf
demselben Dateisystem, mindestens `3 * DB-Größe + 1 GiB` frei halten. Bei
getrennten Dateisystemen auf dem DB-Dateisystem mindestens
`2 * DB-Größe + 1 GiB`, auf dem Backup-Dateisystem mindestens
`1 * DB-Größe + 1 GiB`. Unterschreitung ist ein harter Stop.

Read-only DB-Prüfung und kritische Counts:

```bash
sqlite3 -readonly "$DB_PATH" <<'SQL' | tee "$EVIDENCE_DIR/db.preflight.before.txt"
PRAGMA query_only=ON;
PRAGMA integrity_check;
PRAGMA foreign_key_check;
SELECT 'alembic_table', COUNT(*) FROM sqlite_master WHERE type='table' AND name='alembic_version';
SELECT 'product_categories', COUNT(*) FROM product_categories;
SELECT 'master_products', COUNT(*) FROM master_products;
SELECT 'product_admin_data', COUNT(*) FROM product_admin_data;
SELECT 'user_profiles', COUNT(*) FROM user_profiles;
SELECT 'user_clients', COUNT(*) FROM user_clients;
SELECT 'favorite_stores', COUNT(*) FROM favorite_stores;
SELECT 'favorite_products', COUNT(*) FROM favorite_products;
SELECT 'shopping_items', COUNT(*) FROM shopping_items;
SQL
sqlite3 -readonly "$DB_PATH" <<'SQL' > "$EVIDENCE_DIR/db.critical-counts.before.txt"
SELECT 'product_categories', COUNT(*) FROM product_categories;
SELECT 'master_products', COUNT(*) FROM master_products;
SELECT 'product_admin_data', COUNT(*) FROM product_admin_data;
SELECT 'user_profiles', COUNT(*) FROM user_profiles;
SELECT 'user_clients', COUNT(*) FROM user_clients;
SELECT 'favorite_stores', COUNT(*) FROM favorite_stores;
SELECT 'favorite_products', COUNT(*) FROM favorite_products;
SELECT 'shopping_items', COUNT(*) FROM shopping_items;
SQL
```

`integrity_check` muss exakt `ok` liefern; `foreign_key_check` darf keine
Zeile liefern. Falls `alembic_table=1`, Revision separat lesen; unbekannte oder
mehrdeutige Revision ist ein Stop:

```bash
if test "$(sqlite3 -readonly "$DB_PATH" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='alembic_version';")" = 1; then
  sqlite3 -readonly "$DB_PATH" 'SELECT version_num FROM alembic_version;'
fi
```

## 3. Backup

Der Apply-Helper erzeugt später das konsistente Backup über die SQLite-Backup-
API und validiert es. Hier nur Ziel und Kapazität vorbereiten; **kein leeres
Backup anlegen**, da der Helper vorhandene Ziele absichtlich ablehnt:

```bash
test -d "$BACKUP_DIR"
stat -c 'path=%n uid=%u gid=%g mode=%a' "$BACKUP_DIR"
test ! -e "$BACKUP_PATH"
test -w "$BACKUP_DIR"
df -Pk "$BACKUP_DIR"
umask 077
printf '%s\n' "$BACKUP_PATH" > "$EVIDENCE_DIR/backup-path.txt"
```

## 4. App stop

Ab hier gilt Wartungsmodus. Alle Compose-Dienste mit Zugriff auf die App
stoppen; externe Worker/Scheduler zusätzlich nach deren verifizierter
Service-Definition stoppen:

```bash
cd "$REPO_DIR"
docker compose stop gateway frontend app
docker compose ps | tee "$EVIDENCE_DIR/compose.stopped.txt"
if lsof "$DB_PATH"; then echo 'STOP: DB ist noch geöffnet' >&2; exit 1; fi
```

Es darf kein Container, Systemd-Dienst, Cronjob oder manueller Prozess mehr
schreiben. Der Script-interne Race-Check (Dateiidentität, Größe, mtime und
SHA-256) ist eine zweite Sicherung, kein Ersatz für den Schreibstopp.

## 5. WAL checkpoint

Nur nach bestätigtem Schreibstopp checkpointen:

```bash
sqlite3 "$DB_PATH" 'PRAGMA wal_checkpoint(TRUNCATE);' \
  | tee "$EVIDENCE_DIR/wal-checkpoint.txt"
for sidecar in "$DB_PATH-wal" "$DB_PATH-shm"; do
  if test -e "$sidecar"; then stat -c 'path=%n size=%s uid=%u gid=%g mode=%a' "$sidecar"; else echo "absent: $sidecar"; fi
done | tee "$EVIDENCE_DIR/db.sidecars.checkpointed.txt"
if test -s "$DB_PATH-wal"; then echo 'STOP: WAL ist nicht leer' >&2; exit 1; fi
if test -s "$DB_PATH-shm"; then echo 'STOP: SHM zeigt noch einen SQLite-Nutzer' >&2; exit 1; fi
```

Erwartung für den Checkpoint ist `0|0|0`. Ein nichtleeres WAL ist immer STOP.
Ein nichtleeres SHM ist ebenfalls STOP, weil der Helper daraus fail-closed auf
einen noch aktiven SQLite-Nutzer schließt. Sidecars nicht blind löschen.

## 6. Legacy Alembic Dry Run

Der Dry Run ist read-only, prüft Integrity, FKs, Revision, WAL/SHM und den
exakten Baseline-Schemaabgleich. Nach dem Sidecar-Preflight werden seine
Prüfverbindungen mit SQLite `immutable=1` geöffnet, damit die WAL-Datenbank
nicht allein durch Lesen wieder eine SHM-Datei erhält. Hash vor/nach muss
gleich sein; kein Backup entsteht:

```bash
cd "$RELEASE_DIR"
sha256sum "$DB_PATH" > "$EVIDENCE_DIR/db.sha256.pre-dry-run.txt"
test ! -e "$BACKUP_PATH"
"$PYTHON_BIN" scripts/prepare_existing_sqlite_for_alembic.py \
  --sqlite-path "$DB_PATH" | tee "$EVIDENCE_DIR/alembic-dry-run.txt"
sha256sum "$DB_PATH" > "$EVIDENCE_DIR/db.sha256.post-dry-run.txt"
diff -u "$EVIDENCE_DIR/db.sha256.pre-dry-run.txt" "$EVIDENCE_DIR/db.sha256.post-dry-run.txt"
test ! -e "$BACKUP_PATH"
```

Erwartung bei historischer Produktion: `DRY RUN`, `initial_revision=unversioned`,
`final_revision=unversioned`, `action=stamp-baseline-and-upgrade`. Bei einer
bereits gestempelten Baseline ist `initial_revision=20260825_01` zulässig. Kein
manuelles `alembic stamp` und kein blindes `alembic upgrade head` verwenden.

## 7. Legacy Alembic Apply

Nur nach expliziter Freigabe der Dry-Run-Ausgabe:

```bash
cd "$RELEASE_DIR"
"$PYTHON_BIN" scripts/prepare_existing_sqlite_for_alembic.py \
  --sqlite-path "$DB_PATH" \
  --apply \
  --backup-path "$BACKUP_PATH" | tee "$EVIDENCE_DIR/alembic-apply.txt"
test -f "$BACKUP_PATH"
sha256sum "$BACKUP_PATH" | tee "$EVIDENCE_DIR/backup.sha256.txt"
```

Der Helper validiert Quelle und Backup, migriert nur eine Staging-Kopie im
gleichen Verzeichnis wie die Source und verwendet erst nach vollständiger
Validierung `os.replace`. Damit ist der Austausch innerhalb desselben
Dateisystems atomar. Neu erzeugte Backup-/Staging-Dateien werden auf
`journal_mode=DELETE` normalisiert, damit keine geerbten WAL/SHM-Handles den
Austausch blockieren; der App-Connection-Hook aktiviert WAL nach Start erneut.
Modus, Timestamps/erweiterte Metadaten sowie auf POSIX
Besitzer und Gruppe werden vor dem Austausch übernommen; kann das nicht
erfolgen, bricht Apply vor dem Austausch ab. Backup-Ziel darf auf einem anderen
Dateisystem liegen, muss aber geschützt, beschreibbar und ausreichend groß
sein.

## 8. DB validation

```bash
sqlite3 -readonly "$DB_PATH" <<'SQL' | tee "$EVIDENCE_DIR/db.validation.after.txt"
PRAGMA query_only=ON;
PRAGMA integrity_check;
PRAGMA foreign_key_check;
SELECT 'revision', version_num FROM alembic_version;
SELECT 'parent_id_columns', COUNT(*) FROM pragma_table_info('product_categories') WHERE name='parent_id';
SELECT 'parent_fk', "table", "from", "to" FROM pragma_foreign_key_list('product_categories') WHERE "from"='parent_id';
SELECT 'parent_index', name FROM pragma_index_list('product_categories') WHERE name='ix_product_categories_parent_id';
SELECT 'product_categories', COUNT(*) FROM product_categories;
SELECT 'master_products', COUNT(*) FROM master_products;
SELECT 'product_admin_data', COUNT(*) FROM product_admin_data;
SELECT 'user_profiles', COUNT(*) FROM user_profiles;
SELECT 'user_clients', COUNT(*) FROM user_clients;
SELECT 'favorite_stores', COUNT(*) FROM favorite_stores;
SELECT 'favorite_products', COUNT(*) FROM favorite_products;
SELECT 'shopping_items', COUNT(*) FROM shopping_items;
SQL
sha256sum "$DB_PATH" | tee "$EVIDENCE_DIR/db.sha256.after.txt"
stat -c 'path=%n size=%s uid=%u gid=%g mode=%a mtime=%y device=%d inode=%i' "$DB_PATH" \
  | tee "$EVIDENCE_DIR/db.stat.after.txt"
stat -c '%u:%g:%a' "$DB_PATH" > "$EVIDENCE_DIR/db.owner-group-mode.after.txt"
diff -u "$EVIDENCE_DIR/db.owner-group-mode.before.txt" "$EVIDENCE_DIR/db.owner-group-mode.after.txt"
sqlite3 -readonly "$DB_PATH" <<'SQL' > "$EVIDENCE_DIR/db.critical-counts.after.txt"
SELECT 'product_categories', COUNT(*) FROM product_categories;
SELECT 'master_products', COUNT(*) FROM master_products;
SELECT 'product_admin_data', COUNT(*) FROM product_admin_data;
SELECT 'user_profiles', COUNT(*) FROM user_profiles;
SELECT 'user_clients', COUNT(*) FROM user_clients;
SELECT 'favorite_stores', COUNT(*) FROM favorite_stores;
SELECT 'favorite_products', COUNT(*) FROM favorite_products;
SELECT 'shopping_items', COUNT(*) FROM shopping_items;
SQL
diff -u "$EVIDENCE_DIR/db.critical-counts.before.txt" "$EVIDENCE_DIR/db.critical-counts.after.txt"
```

Erwartung: `ok`, null FK-Zeilen, Revision `20260825_02`, genau eine
`parent_id`-Spalte. Alle kritischen Row-Counts müssen dem Vorher-Protokoll
entsprechen. `uid`, `gid` und `mode` müssen unverändert sein. Die SHA ändert
sich erwartbar durch Schema und Alembic-Version.

Das Backup selbst erneut read-only prüfen:

```bash
sqlite3 -readonly "$BACKUP_PATH" 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

## 9. Code update

Der Ziel-SHA muss zu diesem Zeitpunkt unverändert aktueller `origin/main` sein:

```bash
cd "$REPO_DIR"
git fetch origin main
test "$(git rev-parse origin/main)" = "$TARGET_SHA"
git switch main
git merge --ff-only origin/main
test "$(git rev-parse HEAD)" = "$TARGET_SHA"
git status --short
```

Bei Dirty Worktree, abweichendem SHA oder Non-Fast-Forward: STOP. Kein Reset,
Stash oder Löschen im Wartungsfenster.

## 10. Docker build

Sprint C ändert Backend und die Frontend-Dateien
`src/data/lokero.ts` sowie `src/services/lokero-api.ts`. Daher sind `app` und
`frontend` neu zu bauen. Gateway-Image und Gateway-Konfiguration wurden durch
Sprint C nicht geändert; kein Gateway-Build ist nötig.

```bash
cd "$REPO_DIR"
docker compose build app frontend | tee "$EVIDENCE_DIR/docker-build.txt"
docker compose images | tee "$EVIDENCE_DIR/images.after-build.txt"
```

## 11. App start

Für den kontrollierten Pfad muss `.env` auf dieselbe SQLite-Datei zeigen.
`AUTO_CREATE_SCHEMA=false` wird empfohlen, sobald die vollständige DB auf
`20260825_02` validiert ist, damit Startup keine Schemaerzeugung übernimmt.
Die App führt selbst kein Alembic-Upgrade beim Start aus. Konfiguration vor dem
Start erneut über `docker compose config` prüfen.

```bash
cd "$REPO_DIR"
docker compose config > "$EVIDENCE_DIR/compose.target.yml"
grep -nE 'DATABASE_URL|AUTO_CREATE_SCHEMA|SCHEDULER_ENABLED' "$EVIDENCE_DIR/compose.target.yml"
docker compose up -d --no-deps app
docker compose ps app
docker compose up -d --no-deps frontend
docker compose up -d --no-deps gateway
docker compose ps | tee "$EVIDENCE_DIR/compose.started.txt"
```

Wenn der reale Produktionsstack zusätzliche Compose-Dateien oder einen anderen
Projekt-Namen verwendet, müssen **dieselben verifizierten `-f`/`-p`-Argumente
in jedem Compose-Befehl** stehen.

## 12. Health

```bash
curl --fail --silent --show-error --max-time 10 \
  -o "$EVIDENCE_DIR/health.json" -w '%{http_code}\n' "$BASE_URL/health"
jq . "$EVIDENCE_DIR/health.json"
```

HTTP muss `200` sein. Ein JSON-Status `degraded` kann fachlich erwartbare
veraltete Collections bedeuten, muss aber vom Verantwortlichen erklärt werden;
DB-/Startup-Probleme sind nie akzeptabel.

## 13. Smoke tests

Zuerst nach vollständig beendetem Startup die Phantom-User-Baseline aufnehmen.
Dann alle GETs mit einer frischen, syntaktisch gültigen Client-ID ausführen:

```bash
sqlite3 -readonly "$DB_PATH" \
  "SELECT 'user_profiles',COUNT(*) FROM user_profiles UNION ALL SELECT 'user_clients',COUNT(*) FROM user_clients;" \
  | tee "$EVIDENCE_DIR/identity.pre-smoke.txt"
export SMOKE_CLIENT='rolloutSmokeClient20260825'
smoke_get() {
  name="$1"; path="$2"
  code="$(curl --silent --show-error --max-time 15 \
    -H "X-LocalPrices-Client: $SMOKE_CLIENT" \
    -o "$EVIDENCE_DIR/smoke-$name.json" -w '%{http_code}' "$BASE_URL$path")"
  printf '%s %s %s\n' "$code" "$name" "$path" | tee -a "$EVIDENCE_DIR/smoke-status.txt"
  test "$code" = 200
}
smoke_get health '/health'
smoke_get bootstrap '/api/bootstrap'
smoke_get products-fisch '/api/products?q=Fisch'
smoke_get products-cola '/api/products?q=Cola'
smoke_get products-kaese '/api/products?q=K%C3%A4se'
smoke_get products-coke '/api/products?q=Coke'
smoke_get products-thun '/api/products?q=Thun'
smoke_get category-fisch '/api/products?category=fisch'
smoke_get category-getraenke '/api/products?category=getraenke'
smoke_get stores '/api/lokero/markets'
smoke_get offers '/api/lokero/offers?limit=20'
smoke_get favorite-products '/api/lokero/favorites/products'
smoke_get favorite-markets '/api/lokero/favorites/markets'
smoke_get shopping-list '/api/bootstrap'
export STORE_ID="$(jq -r '.markets[0].id // empty' "$EVIDENCE_DIR/smoke-bootstrap.json")"
if test -n "$STORE_ID"; then smoke_get store-offers "/api/stores/$STORE_ID/offers"; else echo 'STOP: kein Store für Store-Offer-Smoke' >&2; exit 1; fi
sqlite3 -readonly "$DB_PATH" \
  "SELECT 'user_profiles',COUNT(*) FROM user_profiles UNION ALL SELECT 'user_clients',COUNT(*) FROM user_clients;" \
  | tee "$EVIDENCE_DIR/identity.post-smoke.txt"
diff -u "$EVIDENCE_DIR/identity.pre-smoke.txt" "$EVIDENCE_DIR/identity.post-smoke.txt"
```

Die Reads decken Stores, Offers, Favoriten und Einkaufsliste (`basket` in
`/api/bootstrap`) ab. Die zwei Identity-Counts müssen identisch sein. Keine
schreibende Smoke-Route verwenden.

## 14. Logs

Unmittelbar nach Start mindestens die letzten 500 Zeilen aller drei Services
und anschließend 15 Minuten live beobachten:

```bash
cd "$REPO_DIR"
docker compose logs --no-color --tail=500 app frontend gateway \
  | tee "$EVIDENCE_DIR/logs.initial.txt"
timeout 15m docker compose logs --no-color --since=1m --follow app frontend gateway \
  | tee "$EVIDENCE_DIR/logs.follow-15m.txt" || test "$?" = 124
grep -Ein 'FOREIGN KEY constraint failed|OperationalError|IntegrityError|database is locked|readonly database|alembic.*error|(missing|no such) column.*parent_id|migration error|SQLAlchemy.*(error|traceback)|Traceback|startup exception' \
  "$EVIDENCE_DIR/logs.initial.txt" "$EVIDENCE_DIR/logs.follow-15m.txt" && exit 1 || true
```

Jeder Treffer wird manuell kontextgeprüft; echte DB-, Schema-, Migration- oder
Startup-Fehler sind Blocker. Nach den ersten 15 Minuten mindestens 60 Minuten
mit erhöhtem Augenmerk auf 5xx-Rate, Container-Restarts, SQLite-Locks,
Latenz und freien Speicher beobachten.

## 15. Reclassification Dry Run

Produktion bekommt in diesem Rollout **ausschließlich den Dry Run**. Kein
`--apply` einplanen:

```bash
cd "$REPO_DIR"
docker compose exec -T -e PYTHONPATH=/app app python scripts/reclassify_products.py \
  | tee "$EVIDENCE_DIR/reclassification-dry-run.txt"
```

Erwartet werden `DRY RUN` und die Summary-Felder `inspected`, `changed`,
`unchanged`, `locked`, `unknown`. Relevante Einträge enthalten ID, Name, alte
und neue Kategorie, Reason und Status. `category_locked` bleibt unangetastet;
`unknown` wird nicht persistiert. Die Ausgabe ist ein Prüfartefakt für einen
separaten, später freizugebenden Apply.

## 16. Post-deploy monitoring

Nach 15, 30 und 60 Minuten jeweils dokumentieren:

```bash
date -u
curl --fail --silent --show-error --max-time 10 "$BASE_URL/health" | jq .
docker compose ps
docker compose logs --no-color --since=15m app frontend gateway \
  | grep -Ein 'FOREIGN KEY constraint failed|OperationalError|IntegrityError|database is locked|readonly database|alembic.*error|parent_id|migration error|SQLAlchemy|Traceback|startup exception' || true
df -Pk "$DB_PATH"
```

Keine Reclassification anwenden, keine Collector-/Scheduler-Änderung und keine
weitere Migration mit diesem Runbook koppeln.

## 17. Rollback

### A. Fehler vor dem DB-Austausch

Der Helper lässt die Source unverändert. Fehlermeldung und vorhandenes Backup
behalten, Hash/Counts prüfen und nicht deployen. Keine Restore-Aktion nötig.

### B. Migration erfolgreich, App noch nicht gestartet

Writer bleiben gestoppt. Backup validieren und über eine Staging-Datei im
Source-Verzeichnis zurückspielen:

```bash
sqlite3 -readonly "$BACKUP_PATH" 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
export FAILED_DB="$DB_PATH.failed.$ROLLOUT_ID"
export RESTORE_TMP="$(dirname "$DB_PATH")/.restore.$ROLLOUT_ID.sqlite3"
cp --preserve=mode,ownership,timestamps -- "$BACKUP_PATH" "$RESTORE_TMP"
chown --reference="$DB_PATH" "$RESTORE_TMP"
chmod --reference="$DB_PATH" "$RESTORE_TMP"
mv -- "$DB_PATH" "$FAILED_DB"
mv -- "$RESTORE_TMP" "$DB_PATH"
sha256sum "$DB_PATH" "$FAILED_DB"
sqlite3 -readonly "$DB_PATH" 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

`RESTORE_TMP` liegt absichtlich im selben Verzeichnis wie `DB_PATH`, damit das
zweite `mv` atomar ist. Die fehlgeschlagene neue DB wird nicht gelöscht.

### C. App gestartet, sofortiger Smoke-Fehler, noch keine produktiven Writes

```bash
cd "$REPO_DIR"
docker compose stop gateway frontend app
if lsof "$DB_PATH"; then echo 'STOP: DB ist noch geöffnet' >&2; exit 1; fi
git switch --detach "$OLD_GIT_SHA"
docker compose build app frontend
```

Nur falls DB-Restore fachlich nötig und nachweislich noch keine neuen Writes
erfolgt sind, anschließend die Befehle aus B ausführen. Danach alte Services
kontrolliert starten und Health/Smokes wiederholen:

```bash
docker compose up -d --no-deps app
docker compose up -d --no-deps frontend
docker compose up -d --no-deps gateway
```

### D. Neue App hat bereits produktive Writes erzeugt

**Kein simples Backup-Restore:** Es würde neue Profile, Favoriten,
Einkaufslisten und weitere Writes verlieren. Sofort Schreibzugriffe stoppen,
die aktuelle DB als forensische Kopie erhalten und zwischen Forward-Fix und
separat entwickelter Daten-Reconciliation entscheiden. Ohne freigegebenen
Reconciliation-Plan nicht auf das alte Backup zurückschalten.

## 18. Stop criteria

Sofort **STOP – nicht weiterdeployen**, wenn mindestens eines gilt:

- falscher/ungeprüfter SHA, Dirty Worktree oder unerwartete Compose-Konfiguration;
- `integrity_check != ok` oder eine Zeile aus `foreign_key_check`;
- unbekannte/mehrdeutige Alembic-Revision oder Schema-Drift;
- Dry Run verändert SHA oder erzeugt ein Backup;
- Backup-Erzeugung/-Validierung scheitert oder Ziel existiert bereits;
- Writer/File-Handles bleiben aktiv, WAL ist nicht checkpointed oder Source
  ändert sich während Apply;
- freier Speicher unterschreitet die Preflight-Grenze;
- Besitzer, Gruppe oder Modus ändern sich unerwartet;
- Migration endet nicht exakt auf `20260825_02`, `parent_id` fehlt oder
  kritische Counts ändern sich;
- Docker-Build oder Container-Health scheitert, `/health` ist nicht HTTP 200;
- ein Smoke ist nicht HTTP 200 oder GET-Smokes erzeugen `user_profiles`/
  `user_clients`;
- Logs zeigen DB-, FK-, Schema-, Alembic-, SQLAlchemy- oder Startup-Fehler;
- Rollback-Zeitfenster, Beobachtungsfähigkeit oder Freigabe ist nicht mehr gegeben.

Bei STOP: Writer gestoppt lassen, Beweise sichern, nichts automatisch
reparieren und anhand Abschnitt 17 entscheiden. Insbesondere weder manuell
stampen noch `reclassify_products.py --apply` ausführen.
