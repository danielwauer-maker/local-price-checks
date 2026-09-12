#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/local-price-checks}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups/local-price-checks}"
TARGET_SHA="${1:-}"
SUCCESS_MARKER="$BACKUP_DIR/.last-successful-release"
DEPLOY_SCRIPT="/tmp/local-price-checks-deploy.sh"

cd "$APP_DIR"

git fetch --prune origin main

if [[ -z "$TARGET_SHA" ]]; then
  TARGET_SHA="$(git rev-parse origin/main)"
fi

if ! git cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null; then
  echo "ERROR: target commit $TARGET_SHA is not available after fetch."
  exit 1
fi

# The repository checkout is not proof that a release reached the running
# containers. A failed build can advance git before compose recreates anything.
# Only a marker written after deploy-production.sh returns healthy is trusted.
if [[ -f "$SUCCESS_MARKER" ]]; then
  LAST_SUCCESSFUL_SHA="$(tr -d '[:space:]' < "$SUCCESS_MARKER")"
  if [[ -z "$LAST_SUCCESSFUL_SHA" ]] \
    || ! git cat-file -e "${LAST_SUCCESSFUL_SHA}^{commit}" 2>/dev/null \
    || ! git merge-base --is-ancestor "$LAST_SUCCESSFUL_SHA" "$TARGET_SHA"; then
    echo "ERROR: invalid successful-release marker: $SUCCESS_MARKER"
    exit 1
  fi

  if [[ "$LAST_SUCCESSFUL_SHA" != "$TARGET_SHA" ]]; then
    echo "Normalizing deployment checkout to last successful release: $LAST_SUCCESSFUL_SHA"
    git checkout main
    git reset --hard "$LAST_SUCCESSFUL_SHA"
  fi
else
  echo "No successful-release marker yet; bootstrapping from the current checkout."
fi

git show "${TARGET_SHA}:scripts/deploy-production.sh" > "$DEPLOY_SCRIPT"
chmod 700 "$DEPLOY_SCRIPT"

# deploy-production.sh performs its own build/migration/recreate/health gates.
# Do not advance the success marker unless all of them complete successfully.
bash "$DEPLOY_SCRIPT" "$TARGET_SHA"

mkdir -p "$BACKUP_DIR"
printf '%s\n' "$TARGET_SHA" > "${SUCCESS_MARKER}.tmp"
mv "${SUCCESS_MARKER}.tmp" "$SUCCESS_MARKER"
echo "Recorded successful production release: $TARGET_SHA"
