#!/usr/bin/env bash
# Unit test for install_frontend_dist_with_asset_grace.sh (no VPS required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/install_frontend_dist_with_asset_grace.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

LIVE="$TMP/live"
NEW1="$TMP/new1"
NEW2="$TMP/new2"
PREV="$TMP/prev-assets"

mkdir -p "$NEW1/assets" "$NEW2/assets"
echo 'index-v1' > "$NEW1/index.html"
echo 'chunk-a' > "$NEW1/assets/MarketingHub-aaa.js"
echo 'vendor-v1' > "$NEW1/assets/vendor-v1.js"

bash "$SCRIPT" "$NEW1" "$LIVE" "$PREV"
test -f "$LIVE/index.html"
test -f "$LIVE/assets/MarketingHub-aaa.js"
test -f "$PREV/MarketingHub-aaa.js"
test ! -d "$NEW1"

# Second deploy: new hashes + grace retain old MarketingHub
echo 'index-v2' > "$NEW2/index.html"
echo 'chunk-b' > "$NEW2/assets/MarketingHub-bbb.js"
echo 'vendor-v2' > "$NEW2/assets/vendor-v2.js"

bash "$SCRIPT" "$NEW2" "$LIVE" "$PREV"
test "$(cat "$LIVE/index.html")" = 'index-v2'
test -f "$LIVE/assets/MarketingHub-bbb.js"
test -f "$LIVE/assets/MarketingHub-aaa.js"  # grace retained
test -f "$LIVE/assets/vendor-v2.js"
# vendor-v1 was in prev snapshot → retained until overwritten by name; different name kept
test -f "$LIVE/assets/vendor-v1.js"
# Next prev snapshot must be *pure* v2 only (not grace leftovers)
test -f "$PREV/MarketingHub-bbb.js"
test ! -f "$PREV/MarketingHub-aaa.js"
test -f "$PREV/vendor-v2.js"
test ! -f "$PREV/vendor-v1.js"

# Third deploy: aaa finally drops from live (not in v2 pure prev, not in v3)
NEW3="$TMP/new3"
mkdir -p "$NEW3/assets"
echo 'index-v3' > "$NEW3/index.html"
echo 'chunk-c' > "$NEW3/assets/MarketingHub-ccc.js"
bash "$SCRIPT" "$NEW3" "$LIVE" "$PREV"
test -f "$LIVE/assets/MarketingHub-ccc.js"
test -f "$LIVE/assets/MarketingHub-bbb.js"  # one-gen grace
test ! -f "$LIVE/assets/MarketingHub-aaa.js"  # dropped after one generation

echo "OK: install_frontend_dist_with_asset_grace"
