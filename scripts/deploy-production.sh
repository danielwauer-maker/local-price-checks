#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/local-price-checks}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8083/health}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups/local-price-checks}"
TARGET_SHA="${1:-}"
PENDING_FILE="$BACKUP_DIR/.pending-schema-release"
APP_STOPPED=0

cd "$APP_DIR"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "ERROR: tracked working tree changes detected; refusing production deploy."
  git status --short
  exit 1
fi

mkdir -p "$BACKUP_DIR"
git fetch --prune origin main

if [[ -z "$TARGET_SHA" ]]; then
  TARGET_SHA="$(git rev-parse origin/main)"
fi

if ! git cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null; then
  echo "ERROR: target commit $TARGET_SHA is not available after fetch."
  exit 1
fi

OLD_SHA="$(git rev-parse HEAD)"
DIFF_BASE="$OLD_SHA"

# A failed controlled schema release may already have fast-forwarded the checkout.
# Preserve the original comparison base externally so a workflow re-run can safely resume.
if [[ "$OLD_SHA" == "$TARGET_SHA" ]]; then
  if [[ -f "$PENDING_FILE" ]]; then
    read -r SAVED_BASE SAVED_TARGET < "$PENDING_FILE" || true
    if [[ "${SAVED_TARGET:-}" == "$TARGET_SHA" && -n "${SAVED_BASE:-}" ]]; then
      DIFF_BASE="$SAVED_BASE"
      echo "Resuming pending schema release from $DIFF_BASE to $TARGET_SHA"
    else
      echo "Already deployed: $TARGET_SHA"
      exit 0
    fi
  else
    echo "Already deployed: $TARGET_SHA"
    exit 0
  fi
fi

if ! git merge-base --is-ancestor "$DIFF_BASE" "$TARGET_SHA"; then
  echo "ERROR: deployment would not be a fast-forward ($DIFF_BASE -> $TARGET_SHA)."
  exit 1
fi

CHANGED_FILES="$(git diff --name-only "$DIFF_BASE" "$TARGET_SHA")"
printf 'Deploying %s -> %s\n' "$DIFF_BASE" "$TARGET_SHA"
printf '%s\n' "$CHANGED_FILES"

SCHEMA_FILES="$(grep -E '^(alembic\.ini|alembic/|migrations/|app/.+migration|app/models\.py$|app/[^/]*_models\.py$)' <<<"$CHANGED_FILES" || true)"
CONTROLLED_SCHEMA_RELEASE=0

if [[ -n "$SCHEMA_FILES" ]]; then
  # This release path is intentionally narrow. Any future schema change must be
  # reviewed and explicitly added instead of silently inheriting this procedure.
  if grep -Fxq 'migrations/versions/20260827_01_sharing_lists_favorites.py' <<<"$SCHEMA_FILES" \
    && ! grep -Evq '^(migrations/versions/20260827_01_sharing_lists_favorites\.py|app/sharing_models\.py)$' <<<"$SCHEMA_FILES"; then
    CONTROLLED_SCHEMA_RELEASE=1
    echo "Controlled schema release recognized: shared lists + friend favorites."
  else
    echo "ERROR: database/schema-related change detected outside the approved controlled release."
    printf '%s\n' "$SCHEMA_FILES"
    exit 42
  fi
fi

FRONTEND=0
APP=0
GATEWAY=0

if grep -q '^frontend-lovable-source/' <<<"$CHANGED_FILES"; then
  FRONTEND=1
fi
if grep -Eq '^(app/|requirements\.txt$|Dockerfile$|pyproject\.toml$)' <<<"$CHANGED_FILES"; then
  APP=1
fi
if grep -Eq '^(deploy/localprices-gateway\.conf$|docker-compose\.ya?ml$)' <<<"$CHANGED_FILES"; then
  GATEWAY=1
fi
if grep -Eq '^docker-compose\.ya?ml$' <<<"$CHANGED_FILES"; then
  FRONTEND=1
  APP=1
fi
if [[ $FRONTEND -eq 0 && $APP -eq 0 && $GATEWAY -eq 0 ]]; then
  if grep -Evq '^(docs/|README\.md$|\.github/|scripts/|\.gitignore$|\.dockerignore$)' <<<"$CHANGED_FILES"; then
    FRONTEND=1
    APP=1
  fi
fi

on_error() {
  rc=$?
  echo "ERROR: production release failed with exit code $rc."
  if [[ $APP_STOPPED -eq 1 ]]; then
    echo "Restarting the previously running app container after failed migration step..."
    docker compose start app || true
  fi
  docker compose ps || true
  exit "$rc"
}
trap on_error ERR

if [[ $CONTROLLED_SCHEMA_RELEASE -eq 1 ]]; then
  printf '%s %s\n' "$DIFF_BASE" "$TARGET_SHA" > "$PENDING_FILE"
fi

# Fast-forward the repository while the existing containers keep serving the old images.
git checkout main
git merge --ff-only "$TARGET_SHA"

# Build everything before taking the backend down so migration downtime stays short.
if [[ $APP -eq 1 ]]; then
  docker compose build app
fi
if [[ $FRONTEND -eq 1 ]]; then
  docker compose build frontend
fi

if [[ $CONTROLLED_SCHEMA_RELEASE -eq 1 ]]; then
  if [[ $APP -ne 1 ]]; then
    echo "ERROR: controlled schema release requires a freshly built app image."
    exit 1
  fi

  DB_PATH="$(docker compose run --rm --no-deps -T app python -c 'from app.config import database_url; u=database_url(); print(u.database if u.get_backend_name()=="sqlite" else "")' | tail -n 1)"
  if [[ -z "$DB_PATH" || "$DB_PATH" != /app/data/* ]]; then
    echo "ERROR: controlled release currently supports only the mounted production SQLite database; resolved path='$DB_PATH'."
    exit 1
  fi

  DB_HOST_PATH="$APP_DIR/data/${DB_PATH#/app/data/}"
  if [[ ! -f "$DB_HOST_PATH" ]]; then
    echo "ERROR: production SQLite database not found at $DB_HOST_PATH"
    exit 1
  fi

  DB_BYTES="$(stat -c %s "$DB_HOST_PATH")"
  AVAILABLE_BYTES="$(df -PB1 "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
  REQUIRED_BYTES=$(( DB_BYTES * 2 + 268435456 ))
  if (( AVAILABLE_BYTES < REQUIRED_BYTES )); then
    echo "ERROR: insufficient free space for verified external backup + migration staging."
    echo "required=$REQUIRED_BYTES available=$AVAILABLE_BYTES database=$DB_BYTES"
    exit 1
  fi

  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  BACKUP_PATH="$BACKUP_DIR/local_price_checks-pre-sharing-$STAMP.sqlite3"

  echo "Stopping backend briefly for an atomic SQLite migration..."
  docker compose stop app
  APP_STOPPED=1

  echo "Checkpointing SQLite WAL..."
  docker compose run --rm --no-deps -T app python -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); r=c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone(); c.close(); print(r)' "$DB_PATH"

  echo "Validating migration in dry-run mode..."
  docker compose run --rm --no-deps -T \
    -v "$BACKUP_DIR:$BACKUP_DIR" \
    app python scripts/prepare_existing_sqlite_for_alembic.py \
    --sqlite-path "$DB_PATH"

  echo "Applying verified migration with external backup..."
  docker compose run --rm --no-deps -T \
    -v "$BACKUP_DIR:$BACKUP_DIR" \
    app python scripts/prepare_existing_sqlite_for_alembic.py \
    --sqlite-path "$DB_PATH" \
    --apply \
    --backup-path "$BACKUP_PATH"

  echo "Schema migration complete. Backup retained at $BACKUP_PATH"
fi

if [[ $APP -eq 1 ]]; then
  docker compose up -d --no-deps --force-recreate app
  APP_STOPPED=0
fi
if [[ $FRONTEND -eq 1 ]]; then
  docker compose up -d --no-deps --force-recreate frontend
fi
if [[ $GATEWAY -eq 1 ]]; then
  docker compose up -d --no-deps --force-recreate gateway
fi

echo "Waiting for production health..."
for attempt in {1..30}; do
  if curl -fsS "$HEALTH_URL" >/tmp/local-price-checks-health.json 2>/dev/null; then
    cat /tmp/local-price-checks-health.json
    echo
    echo "Production healthy at $TARGET_SHA"
    docker compose ps
    if [[ $CONTROLLED_SCHEMA_RELEASE -eq 1 ]]; then
      rm -f "$PENDING_FILE"
    fi
    trap - ERR
    exit 0
  fi
  sleep 2
done

echo "ERROR: health check failed after 60 seconds."
docker compose ps
docker compose logs --tail=100 app frontend gateway || true
exit 1
