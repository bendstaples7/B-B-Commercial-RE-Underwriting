#!/usr/bin/env bash
# install_frontend_dist_with_asset_grace.sh
#
# Install a CI-built SPA dist while retaining the previous build's hashed
# /assets files for one deploy generation. Open tabs that still reference old
# chunk URLs keep working until they refresh.
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
#   1. Snapshot NEW/assets → PREV_ASSETS.next (pure this-build hashes only)
#   2. Overlay previous PREV_ASSETS into NEW/assets (no overwrite)
#   3. Stage the complete tree under dist-releases/<id>
#   4. Atomically switch LIVE_DIST symlink to the new release (nginx path never
#      vanishes; no in-place partial tree)
#   5. Leave PREV_ASSETS.next for deploy.sh to promote AFTER full success

set -euo pipefail

NEW_DIST="${1:?new dist dir required}"
LIVE_DIST="${2:?live dist dir required}"
PREV_ASSETS="${3:-/home/deploy/frontend-assets-prev}"
PREV_ASSETS_NEXT="${PREV_ASSETS}.next"

if [[ ! -d "$NEW_DIST" ]]; then
  echo "FAILED: new dist missing: $NEW_DIST" >&2
  exit 1
fi
if [[ ! -f "$NEW_DIST/index.html" ]]; then
  echo "FAILED: new dist has no index.html: $NEW_DIST" >&2
  exit 1
fi

# Resolve to absolute paths so the LIVE symlink target is stable regardless of cwd.
LIVE_DIST="$(cd "$(dirname "$LIVE_DIST")" && pwd)/$(basename "$LIVE_DIST")"
NEW_DIST="$(cd "$NEW_DIST" && pwd)"
LIVE_PARENT="$(dirname "$LIVE_DIST")"
LIVE_BASE="$(basename "$LIVE_DIST")"
RELEASES_DIR="${LIVE_PARENT}/${LIVE_BASE}-releases"
RELEASE_ID="$(date -u +%Y%m%d%H%M%S)-$$"
RELEASE_DIR="${RELEASES_DIR}/${RELEASE_ID}"

mkdir -p "$NEW_DIST/assets"
mkdir -p "$RELEASES_DIR"

# Pure asset snapshot for the *next* grace window (before overlay).
# Written to .next so a failed deploy can leave PREV_ASSETS untouched.
rm -rf "$PREV_ASSETS_NEXT"
mkdir -p "$PREV_ASSETS_NEXT"
if compgen -G "$NEW_DIST/assets/*" > /dev/null; then
  cp -a "$NEW_DIST/assets/." "$PREV_ASSETS_NEXT/"
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

# Stage complete tree as a new release directory (never mutate the live tree).
rm -rf "$RELEASE_DIR"
mv "$NEW_DIST" "$RELEASE_DIR"

# First-time migration: if LIVE is a real directory, move it aside so we can
# replace it with a symlink without a missing-path window for long.
if [[ -e "$LIVE_DIST" && ! -L "$LIVE_DIST" ]]; then
  LEGACY="${RELEASES_DIR}/legacy-pre-symlink-$$"
  mv "$LIVE_DIST" "$LEGACY"
  echo "    Migrated plain ${LIVE_DIST} → ${LEGACY} (now symlink-published)"
fi

# Atomic publish: write temp symlink then rename over LIVE (replaces prior link).
TMP_LINK="${LIVE_PARENT}/.${LIVE_BASE}.newlink.$$"
ln -sfn "$RELEASE_DIR" "$TMP_LINK"
mv -Tf "$TMP_LINK" "$LIVE_DIST"

# Keep the newest 3 releases; drop older ones (grace assets still cover one gen).
if command -v python3 >/dev/null 2>&1; then
  python3 - "$RELEASES_DIR" "$RELEASE_DIR" <<'PY'
import os, shutil, sys
releases_dir, keep = sys.argv[1], sys.argv[2]
entries = []
for name in os.listdir(releases_dir):
    path = os.path.join(releases_dir, name)
    if os.path.isdir(path):
        entries.append((os.path.getmtime(path), path))
entries.sort(reverse=True)
for _, path in entries[3:]:
    if os.path.abspath(path) == os.path.abspath(keep):
        continue
    shutil.rmtree(path, ignore_errors=True)
PY
fi

echo "    Frontend dist installed with one-generation asset grace → ${LIVE_DIST} -> ${RELEASE_DIR}"
echo "    Deferred PREV_ASSETS promote: ${PREV_ASSETS_NEXT} (deploy.sh promotes after success)"
