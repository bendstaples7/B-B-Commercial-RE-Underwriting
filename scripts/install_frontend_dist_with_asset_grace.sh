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
#   3. rsync into LIVE so the served path never disappears mid-deploy
#   4. Leave PREV_ASSETS.next for deploy.sh to promote AFTER success
#      (rollback must not leave PREV_ASSETS pointing at a failed release)

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

mkdir -p "$NEW_DIST/assets"

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

# Publish without removing LIVE: rsync keeps the nginx path always present.
mkdir -p "$LIVE_DIST"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "$NEW_DIST"/ "$LIVE_DIST"/
else
  # Fallback when rsync is unavailable: copy then prune (path never missing).
  cp -a "$NEW_DIST"/. "$LIVE_DIST"/
  # Remove live files that are not in the new tree (best-effort; keep assets
  # that only exist via grace overlay already present in NEW).
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$NEW_DIST" "$LIVE_DIST" <<'PY'
import os, sys
new, live = sys.argv[1], sys.argv[2]
new_files = set()
for root, dirs, files in os.walk(new):
    rel = os.path.relpath(root, new)
    for name in files:
        new_files.add(os.path.normpath(os.path.join(rel, name)))
for root, dirs, files in os.walk(live, topdown=False):
    rel = os.path.relpath(root, live)
    for name in files:
        path_rel = os.path.normpath(os.path.join(rel, name))
        if path_rel not in new_files:
            os.remove(os.path.join(root, name))
    for name in dirs:
        d = os.path.join(root, name)
        try:
            os.rmdir(d)
        except OSError:
            pass
PY
  fi
fi
rm -rf "$NEW_DIST"

echo "    Frontend dist installed with one-generation asset grace → ${LIVE_DIST}"
echo "    Deferred PREV_ASSETS promote: ${PREV_ASSETS_NEXT} (deploy.sh promotes after success)"
