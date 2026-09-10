#!/usr/bin/env bash
# Failure-path unit test for PREV_ASSETS promote/restore.
# Sources the production helper (prev_assets_promote.sh) — does not re-implement it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=prev_assets_promote.sh
source "$ROOT/scripts/prev_assets_promote.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
HOME_DEPLOY="$TMP/home/deploy"
mkdir -p "$HOME_DEPLOY"

PREV="$HOME_DEPLOY/frontend-assets-prev"
PREV_NEXT="$HOME_DEPLOY/frontend-assets-prev.next"
PREV_ROLLBACK="$HOME_DEPLOY/frontend-assets-prev.rollback"

# --- Case 1: failure before any promote mutation — keep live grace + leftover .rollback
rm -rf "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
mkdir -p "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
echo current > "$PREV/chunk.js"
echo stale > "$PREV_ROLLBACK/chunk.js"
echo next > "$PREV_NEXT/chunk.js"
set +e
PREV_ASSETS_PROMOTE_FAIL_AFTER=before_rm_rollback promote_prev_assets "$HOME_DEPLOY"
rc=$?
set -e
unset PREV_ASSETS_PROMOTE_FAIL_AFTER
test "$rc" -eq 41
restore_prev_assets_if_promote_started "$HOME_DEPLOY"
test "$(cat "$PREV/chunk.js")" = "current"
test "$(cat "$PREV_ROLLBACK/chunk.js")" = "stale"

# --- Case 2: failure after clearing old .rollback but before moving live —
# live grace preserved; flag stays 0 so restore is a no-op
rm -rf "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
mkdir -p "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
echo current > "$PREV/chunk.js"
echo stale > "$PREV_ROLLBACK/chunk.js"
echo next > "$PREV_NEXT/chunk.js"
set +e
PREV_ASSETS_PROMOTE_FAIL_AFTER=before_mv_live promote_prev_assets "$HOME_DEPLOY"
rc=$?
set -e
unset PREV_ASSETS_PROMOTE_FAIL_AFTER
test "$rc" -eq 42
restore_prev_assets_if_promote_started "$HOME_DEPLOY"
test "$(cat "$PREV/chunk.js")" = "current"
test ! -d "$PREV_ROLLBACK"

# --- Case 3: failure after moving live prev — restore .rollback (just-moved live set)
rm -rf "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
mkdir -p "$PREV" "$PREV_NEXT"
echo current > "$PREV/chunk.js"
echo next > "$PREV_NEXT/chunk.js"
set +e
PREV_ASSETS_PROMOTE_FAIL_AFTER=after_mv_live promote_prev_assets "$HOME_DEPLOY"
rc=$?
set -e
unset PREV_ASSETS_PROMOTE_FAIL_AFTER
test "$rc" -eq 43
test ! -d "$PREV"
test -f "$PREV_ROLLBACK/chunk.js"
restore_prev_assets_if_promote_started "$HOME_DEPLOY"
test "$(cat "$PREV/chunk.js")" = "current"
test ! -d "$PREV_ROLLBACK"

# --- Case 4: full promote success
rm -rf "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
mkdir -p "$PREV" "$PREV_NEXT"
echo current > "$PREV/chunk.js"
echo next > "$PREV_NEXT/chunk.js"
promote_prev_assets "$HOME_DEPLOY"
test "$(cat "$PREV/chunk.js")" = "next"
test "$(cat "$PREV_ROLLBACK/chunk.js")" = "current"

# --- Case 5: post-deploy unconditional restore
restore_prev_assets_from_rollback "$HOME_DEPLOY"
test "$(cat "$PREV/chunk.js")" = "current"
test ! -d "$PREV_ROLLBACK"

# --- Case 6: interrupted promote left prev missing + .rollback present —
# retry must restore .rollback before replacing it (resumable promote)
rm -rf "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
mkdir -p "$PREV_ROLLBACK" "$PREV_NEXT"
echo interrupted-live > "$PREV_ROLLBACK/chunk.js"
echo next2 > "$PREV_NEXT/chunk.js"
promote_prev_assets "$HOME_DEPLOY"
test "$(cat "$PREV/chunk.js")" = "next2"
test "$(cat "$PREV_ROLLBACK/chunk.js")" = "interrupted-live"

echo "OK: prev_assets_promote_rollback"
