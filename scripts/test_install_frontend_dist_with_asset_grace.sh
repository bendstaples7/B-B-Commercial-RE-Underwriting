#!/usr/bin/env bash
# Unit test for install_frontend_dist_with_asset_grace.sh (no VPS required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/install_frontend_dist_with_asset_grace.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

promote_prev() {
  local prev="$1"
  # Mirror deploy.sh: save .rollback then promote .next only after "success".
  if [[ -d "${prev}.next" ]]; then
    rm -rf "${prev}.rollback"
    if [[ -d "$prev" ]]; then
      mv "$prev" "${prev}.rollback"
    fi
    mv "${prev}.next" "$prev"
  fi
}

LIVE="$TMP/live"
NEW1="$TMP/new1"
NEW2="$TMP/new2"
PREV="$TMP/prev-assets"

# Start with a plain directory LIVE (pre-symlink era) to exercise atomic migration.
mkdir -p "$LIVE/assets" "$NEW1/assets" "$NEW2/assets"
echo 'index-old' > "$LIVE/index.html"
echo 'chunk-old' > "$LIVE/assets/old.js"
echo 'index-v1' > "$NEW1/index.html"
echo 'chunk-a' > "$NEW1/assets/MarketingHub-aaa.js"
echo 'vendor-v1' > "$NEW1/assets/vendor-v1.js"

bash "$SCRIPT" "$NEW1" "$LIVE" "$PREV"
promote_prev "$PREV"
# Live path must be a symlink to a release dir (atomic publish).
test -L "$LIVE"
test -f "$LIVE/index.html"
test "$(cat "$LIVE/index.html")" = 'index-v1'
test -f "$LIVE/assets/MarketingHub-aaa.js"
test -f "$PREV/MarketingHub-aaa.js"
test ! -d "$NEW1"
test ! -d "${PREV}.next"
test -d "${LIVE}-releases"
# Legacy plain tree retained under releases (migration).
compgen -G "${LIVE}-releases/legacy-pre-symlink-*" > /dev/null

# Second deploy: new hashes + grace retain old MarketingHub
echo 'index-v2' > "$NEW2/index.html"
echo 'chunk-b' > "$NEW2/assets/MarketingHub-bbb.js"
echo 'vendor-v2' > "$NEW2/assets/vendor-v2.js"

bash "$SCRIPT" "$NEW2" "$LIVE" "$PREV"
# Before promote, PREV still holds v1 (rollback-safe).
test -f "$PREV/MarketingHub-aaa.js"
test -f "${PREV}.next/MarketingHub-bbb.js"
test ! -f "${PREV}.next/MarketingHub-aaa.js"
promote_prev "$PREV"

test "$(cat "$LIVE/index.html")" = 'index-v2'
test -f "$LIVE/assets/MarketingHub-bbb.js"
test -f "$LIVE/assets/MarketingHub-aaa.js"  # grace retained
test -f "$LIVE/assets/vendor-v2.js"
test -f "$LIVE/assets/vendor-v1.js"
# After promote, prev snapshot must be *pure* v2 only
test -f "$PREV/MarketingHub-bbb.js"
test ! -f "$PREV/MarketingHub-aaa.js"
test -f "$PREV/vendor-v2.js"
test ! -f "$PREV/vendor-v1.js"
# .rollback holds pre-promotion grace (post-deploy rollback restore source)
test -f "${PREV}.rollback/MarketingHub-aaa.js"

# Third deploy: aaa finally drops from live (not in v2 pure prev, not in v3)
NEW3="$TMP/new3"
mkdir -p "$NEW3/assets"
echo 'index-v3' > "$NEW3/index.html"
echo 'chunk-c' > "$NEW3/assets/MarketingHub-ccc.js"
bash "$SCRIPT" "$NEW3" "$LIVE" "$PREV"
promote_prev "$PREV"
test -f "$LIVE/assets/MarketingHub-ccc.js"
test -f "$LIVE/assets/MarketingHub-bbb.js"  # one-gen grace
test ! -f "$LIVE/assets/MarketingHub-aaa.js"  # dropped after one generation

# Failed-deploy simulation: install writes .next but we do NOT promote —
# PREV stays on the last good generation.
NEW4="$TMP/new4"
mkdir -p "$NEW4/assets"
echo 'index-v4' > "$NEW4/index.html"
echo 'chunk-d' > "$NEW4/assets/MarketingHub-ddd.js"
bash "$SCRIPT" "$NEW4" "$LIVE" "$PREV"
test -f "${PREV}.next/MarketingHub-ddd.js"
test -f "$PREV/MarketingHub-ccc.js"  # last good still intact
test ! -f "$PREV/MarketingHub-ddd.js"
rm -rf "${PREV}.next"  # rollback would discard .next

# Prune protection: current live symlink target must survive many installs.
for i in 5 6 7 8; do
  N="$TMP/new$i"
  mkdir -p "$N/assets"
  echo "index-v$i" > "$N/index.html"
  echo "chunk-$i" > "$N/assets/MarketingHub-$i.js"
  bash "$SCRIPT" "$N" "$LIVE" "$PREV"
  promote_prev "$PREV"
done
test -d "$(readlink -f "$LIVE")"
test -f "$LIVE/index.html"

echo "OK: install_frontend_dist_with_asset_grace"
