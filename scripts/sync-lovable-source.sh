#!/usr/bin/env bash
set -euo pipefail

APPLY=false
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--apply" ]]; then
    APPLY=true
  else
    ARGS+=("$arg")
  fi
done

SOURCE_REPO="${ARGS[0]:-https://github.com/danielwauer-maker/price-radar-app-81-960e2446.git}"
SOURCE_BRANCH="${ARGS[1]:-main}"
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

echo "Source commit: $SOURCE_SHA"

if [[ "$APPLY" != "true" ]]; then
  echo
  echo "SAFE MODE: no files were changed."
  echo "Lovable is not allowed to overwrite the production frontend without explicit approval."
  echo "To apply a reviewed sync intentionally, run:"
  echo "  ./scripts/sync-lovable-source.sh --apply"
  exit 0
fi

echo
echo "APPLY MODE: approved Lovable sync is being applied."

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
  --exclude='public/brand/' \
  --exclude='public/favicon.ico' \
  --exclude='public/manifest.webmanifest' \
  --exclude='src/components/brand/' \
  --exclude='src/brand.css' \
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
Protected Spareno branding preserved by the sync: \`public/brand/\`, \`public/favicon.ico\`,
\`public/manifest.webmanifest\`, \`src/components/brand/\`, \`src/brand.css\`.

The sync is safe-mode by default and only writes files when explicitly invoked with \`--apply\`.
EOF

echo
echo "Lovable source synced successfully."
echo "Source commit: $SOURCE_SHA"
echo "Review with: git status --short frontend-lovable-source"
