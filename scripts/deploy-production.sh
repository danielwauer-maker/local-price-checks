#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/local-price-checks}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8083/health}"
TARGET_SHA="${1:-}"

cd "$APP_DIR"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "ERROR: tracked working tree changes detected; refusing production deploy."
  git status --short
  exit 1
fi

OLD_SHA="$(git rev-parse HEAD)"
git fetch --prune origin main

if [[ -z "$TARGET_SHA" ]]; then
  TARGET_SHA="$(git rev-parse origin/main)"
fi

if ! git cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null; then
  echo "ERROR: target commit $TARGET_SHA is not available after fetch."
  exit 1
fi

if ! git merge-base --is-ancestor "$OLD_SHA" "$TARGET_SHA"; then
  echo "ERROR: deployment would not be a fast-forward ($OLD_SHA -> $TARGET_SHA)."
  exit 1
fi

if [[ "$OLD_SHA" == "$TARGET_SHA" ]]; then
  echo "Already deployed: $TARGET_SHA"
  exit 0
fi

CHANGED_FILES="$(git diff --name-only "$OLD_SHA" "$TARGET_SHA")"
printf 'Deploying %s -> %s\n' "$OLD_SHA" "$TARGET_SHA"
printf '%s\n' "$CHANGED_FILES"

# Database schema changes deliberately require a manual production release.
# Catch every SQLAlchemy model module, not only the two legacy model files.
if grep -Eq '^(alembic\.ini|alembic/|migrations/|app/.+migration|app/models\.py$|app/[^/]*_models\.py$)' <<<"$CHANGED_FILES"; then
  echo "ERROR: database/schema-related change detected. Manual deployment approval required."
  exit 42
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

# Unknown application-impacting changes: choose safety over cleverness.
if [[ $FRONTEND -eq 0 && $APP -eq 0 && $GATEWAY -eq 0 ]]; then
  if grep -Evq '^(docs/|README\.md$|\.github/|scripts/|\.gitignore$|\.dockerignore$)' <<<"$CHANGED_FILES"; then
    FRONTEND=1
    APP=1
  fi
fi

git checkout main
git merge --ff-only "$TARGET_SHA"

if [[ $APP -eq 1 ]]; then
  docker compose build app
fi

if [[ $FRONTEND -eq 1 ]]; then
  docker compose build frontend
fi

if [[ $APP -eq 1 ]]; then
  docker compose up -d --no-deps --force-recreate app
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
    exit 0
  fi
  sleep 2
done

echo "ERROR: health check failed after 60 seconds."
docker compose ps
docker compose logs --tail=80 app frontend gateway || true
exit 1
