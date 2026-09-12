#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/local-price-checks}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups/local-price-checks}"
TARGET_SHA="${1:-}"
SUCCESS_MARKER="$BACKUP_DIR/.last-successful-release"
DEPLOY_SCRIPT="/tmp/local-price-checks-deploy.sh"
DISK_SAFETY_SCRIPT="/tmp/local-price-checks-production-disk-safety.sh"
FORCE_FULL_REDEPLOY=0
MARKER_VERSION="v2"

cd "$APP_DIR"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "ERROR: tracked working tree changes detected; refusing production release normalization."
  git status --short
  exit 1
fi

git fetch --prune origin main

if [[ -z "$TARGET_SHA" ]]; then
  TARGET_SHA="$(git rev-parse origin/main)"
fi

if ! git cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null; then
  echo "ERROR: target commit $TARGET_SHA is not available after fetch."
  exit 1
fi

# A repository checkout is not proof that a release reached the running
# containers. Only a versioned marker written after a verified deploy is
# trusted as deployment truth. Legacy/plain markers are intentionally treated
# as unverified because an older wrapper could record them after an
# "Already deployed" short-circuit without recreating stale containers.
if [[ -f "$SUCCESS_MARKER" ]]; then
  MARKER_CONTENT="$(tr -d '\r\n' < "$SUCCESS_MARKER")"
  LAST_SUCCESSFUL_SHA=""

  if [[ "$MARKER_CONTENT" == "$MARKER_VERSION "* ]]; then
    LAST_SUCCESSFUL_SHA="${MARKER_CONTENT#"$MARKER_VERSION "}"
  else
    LAST_SUCCESSFUL_SHA="$MARKER_CONTENT"
    FORCE_FULL_REDEPLOY=1
    echo "Legacy/unverified successful-release marker detected; forcing a full redeploy."
  fi

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
  elif [[ $FORCE_FULL_REDEPLOY -eq 1 ]]; then
    echo "Checkout already matches unverified marker target; deploy will still rebuild and recreate production services."
  fi
else
  # First bootstrap cannot trust the checkout because a prior failed deployment
  # may have advanced git before compose recreated the running services.
  FORCE_FULL_REDEPLOY=1
  echo "No verified successful-release marker yet; forcing a full bootstrap deploy."
fi

git show "${TARGET_SHA}:scripts/deploy-production.sh" > "$DEPLOY_SCRIPT"
git show "${TARGET_SHA}:scripts/production-disk-safety.sh" > "$DISK_SAFETY_SCRIPT"
chmod 700 "$DEPLOY_SCRIPT"
chmod 700 "$DISK_SAFETY_SCRIPT"

# deploy-production.sh performs its own build/migration/recreate/health gates.
# A bootstrap/unverified marker explicitly forces app+frontend+gateway rebuild
# and recreation so an identical checkout cannot be mistaken for a release.
DISK_SAFETY_SCRIPT="$DISK_SAFETY_SCRIPT" FORCE_FULL_REDEPLOY="$FORCE_FULL_REDEPLOY" bash "$DEPLOY_SCRIPT" "$TARGET_SHA"

mkdir -p "$BACKUP_DIR"
printf '%s %s\n' "$MARKER_VERSION" "$TARGET_SHA" > "${SUCCESS_MARKER}.tmp"
mv "${SUCCESS_MARKER}.tmp" "$SUCCESS_MARKER"
echo "Recorded verified production release: $TARGET_SHA"
