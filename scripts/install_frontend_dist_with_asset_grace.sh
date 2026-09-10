#!/usr/bin/env bash
# install_frontend_dist_with_asset_grace.sh
#
# Atomically install a CI-built SPA dist while retaining the previous build's
# hashed /assets files for one deploy generation. Open tabs that still
# reference old chunk URLs keep working until they refresh.
#
# Usage:
#   bash install_frontend_dist_with_asset_grace.sh \
#     <NEW_DIST> <LIVE_DIST> [PREV_ASSETS_DIR]
#
# Example (from deploy.sh):
#   bash scripts/install_frontend_dist_with_asset_grace.sh \
#     /home/deploy/frontend-dist frontend/dist /home/deploy/frontend-assets-prev
#
# Flow:
#   1. Snapshot NEW/assets → next PREV_ASSETS (pure this-build hashes only)
#   2. Overlay previous PREV_ASSETS into NEW/assets (no overwrite)
#   3. Atomic rename swap LIVE ← NEW
#   4. Publish the pure snapshot as PREV_ASSETS for the next deploy

set -euo pipefail

NEW_DIST="${1:?new dist dir required}"
LIVE_DIST="${2:?live dist dir required}"
PREV_ASSETS="${3:-/home/deploy/frontend-assets-prev}"

if [[ ! -d "$NEW_DIST" ]]; then
  echo "FAILED: new dist missing: $NEW_DIST" >&2
  exit 1
fi
if [[ ! -f "$NEW_DIST/index.html" ]]; then
  echo "FAILED: new dist has no index.html: $NEW_DIST" >&2
  exit 1
fi

LIVE_PARENT="$(dirname "$LIVE_DIST")"
LIVE_BASE="$(basename "$LIVE_DIST")"
TMP_PREV="${PREV_ASSETS}.next.$$"
OLD_LIVE="${LIVE_PARENT}/.${LIVE_BASE}.old.$$"

cleanup() {
  rm -rf "$TMP_PREV" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "$NEW_DIST/assets"

# Pure asset snapshot for the *next* deploy's grace window (before overlay).
rm -rf "$TMP_PREV"
mkdir -p "$TMP_PREV"
if compgen -G "$NEW_DIST/assets/*" > /dev/null; then
  cp -a "$NEW_DIST/assets/." "$TMP_PREV/"
fi

# Overlay previous generation's hashed files (never replace newer hashes).
GRACE_COPIED=0
if [[ -d "$PREV_ASSETS" ]]; then
  shopt -s nullglob
  for src in "$PREV_ASSETS"/*; do
    [[ -f "$src" ]] || continue
    name="$(basename "$src")"
    dest="$NEW_DIST/assets/$name"
    if [[ -e "$dest" ]]; then
      continue
    fi
    cp -a "$src" "$dest"
    GRACE_COPIED=$((GRACE_COPIED + 1))
  done
  shopt -u nullglob
  echo "    Asset grace: retained ${GRACE_COPIED} prior hashed file(s) from ${PREV_ASSETS}"
else
  echo "    Asset grace: no prior asset dir (${PREV_ASSETS}) — first install or cold start"
fi

# Atomic swap: NEW → LIVE, keep OLD briefly then drop (rollback uses frontend-dist-backup).
rm -rf "$OLD_LIVE"
if [[ -d "$LIVE_DIST" ]]; then
  mv "$LIVE_DIST" "$OLD_LIVE"
fi
mv "$NEW_DIST" "$LIVE_DIST"
rm -rf "$OLD_LIVE"

# Publish pure this-build assets as the grace source for the next deploy.
rm -rf "$PREV_ASSETS"
mv "$TMP_PREV" "$PREV_ASSETS"
TMP_PREV=""  # owned by PREV_ASSETS now; skip cleanup rm

echo "    Frontend dist installed with one-generation asset grace → ${LIVE_DIST}"
