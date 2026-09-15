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

safe_postdeploy_cleanup() {
  local marker="${PRODUCTION_DOCKER_CLEANUP_MARKER:-/opt/backups/local-price-checks/.docker-storage-cleanup-20260915}"
  local retired_image="${PRODUCTION_RETIRED_IMAGE_TAG:-local-price-checks-app:rollback-20260915}"
  local cleanup_complete=1
  local image_id=""
  local image_in_use=0
  local container_id=""

  if [[ -f "$marker" ]]; then
    echo "Docker storage cleanup already completed; skipping one-time cleanup."
    log_production_storage "after skipped one-time Docker storage cleanup"
    return 0
  fi

  if docker image inspect "$retired_image" >/dev/null 2>&1; then
    image_id="$(docker image inspect --format '{{.Id}}' "$retired_image" 2>/dev/null || true)"
    if [[ -z "$image_id" ]]; then
      echo "Could not resolve retired rollback image ID; cleanup will be retried on a future deploy."
      cleanup_complete=0
    else
      while IFS= read -r container_id; do
        [[ -z "$container_id" ]] && continue
        if [[ "$(docker inspect --format '{{.Image}}' "$container_id" 2>/dev/null || true)" == "$image_id" ]]; then
          image_in_use=1
          break
        fi
      done < <(docker ps -aq 2>/dev/null || true)

      if [[ "$image_in_use" -eq 1 ]]; then
        echo "Retired rollback image is still referenced by a container; keeping it for safety."
        cleanup_complete=0
      elif docker image rm "$retired_image"; then
        echo "Removed retired rollback image tag: $retired_image"
      else
        echo "Could not remove retired rollback image tag; cleanup will be retried on a future deploy."
        cleanup_complete=0
      fi
    fi
  else
    echo "Retired rollback image tag is already absent."
  fi

  if ! docker builder prune -af; then
    echo "Docker build-cache cleanup failed; cleanup will be retried on a future deploy."
    cleanup_complete=0
  fi

  if ! docker image prune -f; then
    echo "Dangling-image cleanup failed; cleanup will be retried on a future deploy."
    cleanup_complete=0
  fi

  if [[ "$cleanup_complete" -eq 1 ]]; then
    if mkdir -p "$(dirname "$marker")" && touch "$marker"; then
      echo "Recorded completed Docker storage cleanup."
    else
      echo "Could not persist Docker cleanup marker; cleanup will be retried on a future deploy."
    fi
  else
    echo "Docker storage cleanup was not fully completed; no completion marker was written."
  fi

  log_production_storage "after one-time Docker storage cleanup"
  return 0
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
