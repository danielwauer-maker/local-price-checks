#!/usr/bin/env bash
set -euo pipefail

SOURCE_REPO="${1:-https://github.com/danielwauer-maker/price-radar-app-81-960e2446.git}"
SOURCE_BRANCH="${2:-main}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$REPO_ROOT/frontend-lovable-source"
TEMP="$(mktemp -d)"

cleanup() {
  rm -rf "$TEMP"
}
trap cleanup EXIT

echo "=== LOVABLE SOURCE SYNC ==="
echo "Source: $SOURCE_REPO ($SOURCE_BRANCH)"
echo "Target: $TARGET"

git clone --depth 1 --branch "$SOURCE_BRANCH" "$SOURCE_REPO" "$TEMP/source"
SOURCE_SHA="$(git -C "$TEMP/source" rev-parse HEAD)"

mkdir -p "$TARGET"
rsync -a --delete \
  --exclude='.git/' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='.lovable/' \
  --exclude='node_modules/' \
  --exclude='dist/' \
  --exclude='.dockerignore' \
  --exclude='Dockerfile.server' \
  "$TEMP/source/" "$TARGET/"

cat > "$TARGET/SOURCE.md" <<EOF
# Lovable frontend source

Controlled snapshot of:
\`danielwauer-maker/price-radar-app-81-960e2446\` (\`$SOURCE_BRANCH\`)

Source commit: \`$SOURCE_SHA\`

This folder is design/frontend source only. The production backend, collectors,
database and Sparplan remain in the Local Price Checks application.

Excluded from the snapshot: \`.git/\`, \`.env*\`, \`.lovable/\`, \`node_modules/\`, \`dist/\`.
Production overlays preserved by the sync: \`.dockerignore\`, \`Dockerfile.server\`.
EOF

echo
echo "Lovable source synced successfully."
echo "Source commit: $SOURCE_SHA"
echo "Review with: git status --short frontend-lovable-source"
