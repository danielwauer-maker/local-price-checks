#!/usr/bin/env bash

# Production deploy disk policy. Keep this file side-effect free when sourced;
# deploy-production.sh decides when cleanup and checks are required.
readonly PRODUCTION_ROOT_PATH="/"
readonly MIN_ROOT_FREE_BYTES=$((7 * 1024 * 1024 * 1024))

log_production_storage() {
  local phase="${1:-production storage}"
  echo "Storage status: $phase"
  df -h "$PRODUCTION_ROOT_PATH" || true
  docker system df || true
}

safe_prebuild_cleanup() {
  log_production_storage "before safe pre-build cleanup"
  echo "Reclaiming unused Docker build cache and dangling images (volumes are never pruned)..."
  docker builder prune -af || true
  docker image prune -f || true
  log_production_storage "after safe pre-build cleanup"
}

require_production_build_space() {
  local available_bytes
  if ! available_bytes="$(df -PB1 "$PRODUCTION_ROOT_PATH" | awk 'NR == 2 {print $4}')"; then
    echo "ERROR: unable to measure free bytes on production root filesystem $PRODUCTION_ROOT_PATH."
    return 1
  fi
  if [[ ! "$available_bytes" =~ ^[0-9]+$ ]]; then
    echo "ERROR: unable to determine free bytes on production root filesystem $PRODUCTION_ROOT_PATH."
    return 1
  fi

  echo "Production build disk preflight: required_free_bytes=$MIN_ROOT_FREE_BYTES available_free_bytes=$available_bytes"
  if (( available_bytes < MIN_ROOT_FREE_BYTES )); then
    echo "ERROR: insufficient free root disk for production build."
    echo "At least 7 GiB must remain free before the build; no containers, images, volumes, databases, or backups were deleted by this check."
    return 1
  fi
  echo "Production build disk preflight passed."
}
