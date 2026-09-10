#!/usr/bin/env bash
# Failure-path unit test for PREV_ASSETS_PROMOTE_STARTED ordering.
# Confirms pre-promote failures keep the live grace set, and mid-promote
# failures restore .rollback only after the live set was moved aside.
set -euo pipefail

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

HOME_DEPLOY="$TMP/home/deploy"
mkdir -p "$HOME_DEPLOY"
PREV="$HOME_DEPLOY/frontend-assets-prev"
PREV_NEXT="$HOME_DEPLOY/frontend-assets-prev.next"
PREV_ROLLBACK="$HOME_DEPLOY/frontend-assets-prev.rollback"

# Mirror deploy.sh promote + ERR restore (paths under TMP).
promote_with_flag() {
  local force_fail_after="${1:-}"
  PREV_ASSETS_PROMOTE_STARTED=0
  if [[ -d "$PREV_NEXT" ]]; then
    if [[ "$force_fail_after" == "before_rm_rollback" ]]; then
      return 41
    fi
    rm -rf "$PREV_ROLLBACK"
    if [[ "$force_fail_after" == "before_mv_live" ]]; then
      return 42
    fi
    if [[ -d "$PREV" ]]; then
      mv "$PREV" "$PREV_ROLLBACK"
      PREV_ASSETS_PROMOTE_STARTED=1
    fi
    if [[ "$force_fail_after" == "after_mv_live" ]]; then
      return 43
    fi
    mv "$PREV_NEXT" "$PREV"
  fi
}

restore_on_err() {
  if [[ "${PREV_ASSETS_PROMOTE_STARTED:-0}" == "1" ]] && [[ -d "$PREV_ROLLBACK" ]]; then
    rm -rf "$PREV"
    mv "$PREV_ROLLBACK" "$PREV"
  fi
  rm -rf "$PREV_NEXT"
}

# --- Case 1: failure before any promote mutation — keep live grace + leftover .rollback
rm -rf "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
mkdir -p "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
echo current > "$PREV/chunk.js"
echo stale > "$PREV_ROLLBACK/chunk.js"
echo next > "$PREV_NEXT/chunk.js"
set +e
promote_with_flag before_rm_rollback
rc=$?
set -e
test "$rc" -eq 41
restore_on_err
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
promote_with_flag before_mv_live
rc=$?
set -e
test "$rc" -eq 42
restore_on_err
test "$(cat "$PREV/chunk.js")" = "current"
test ! -d "$PREV_ROLLBACK"  # cleared; must not resurrect stale

# --- Case 3: failure after moving live prev — restore .rollback (just-moved live set)
rm -rf "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
mkdir -p "$PREV" "$PREV_NEXT"
echo current > "$PREV/chunk.js"
echo next > "$PREV_NEXT/chunk.js"
set +e
promote_with_flag after_mv_live
rc=$?
set -e
test "$rc" -eq 43
test ! -d "$PREV"
test -f "$PREV_ROLLBACK/chunk.js"
restore_on_err
test "$(cat "$PREV/chunk.js")" = "current"
test ! -d "$PREV_ROLLBACK"

# --- Case 4: full promote success
rm -rf "$PREV" "$PREV_NEXT" "$PREV_ROLLBACK"
mkdir -p "$PREV" "$PREV_NEXT"
echo current > "$PREV/chunk.js"
echo next > "$PREV_NEXT/chunk.js"
promote_with_flag
test "$(cat "$PREV/chunk.js")" = "next"
test "$(cat "$PREV_ROLLBACK/chunk.js")" = "current"

echo "OK: prev_assets_promote_rollback_flag"
