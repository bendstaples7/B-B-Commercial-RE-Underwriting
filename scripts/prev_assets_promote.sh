#!/usr/bin/env bash
# prev_assets_promote.sh — shared PREV_ASSETS promote / ERR-restore helpers.
#
# Sourced by deploy.sh (production) and test_prev_assets_promote_rollback.sh.
# Keep promote + guarded restore in ONE place so CI cannot green a parallel mirror.
#
# Optional test hook: PREV_ASSETS_PROMOTE_FAIL_AFTER=
#   before_rm_rollback | before_mv_live | after_mv_live

# Promote deferred grace assets after a successful deploy.
# Sets PREV_ASSETS_PROMOTE_STARTED=1 only after the live set is moved to .rollback.
promote_prev_assets() {
  local root="${1:-/home/deploy}"
  local prev="${root}/frontend-assets-prev"
  local next="${root}/frontend-assets-prev.next"
  local rollback="${root}/frontend-assets-prev.rollback"

  PREV_ASSETS_PROMOTE_STARTED=0

  if [[ ! -d "$next" ]]; then
    return 0
  fi

  if [[ "${PREV_ASSETS_PROMOTE_FAIL_AFTER:-}" == "before_rm_rollback" ]]; then
    return 41
  fi

  rm -rf "$rollback"

  if [[ "${PREV_ASSETS_PROMOTE_FAIL_AFTER:-}" == "before_mv_live" ]]; then
    return 42
  fi

  if [[ -d "$prev" ]]; then
    mv "$prev" "$rollback"
    # Live grace is now only in .rollback — enable ERR restore.
    PREV_ASSETS_PROMOTE_STARTED=1
  fi

  if [[ "${PREV_ASSETS_PROMOTE_FAIL_AFTER:-}" == "after_mv_live" ]]; then
    return 43
  fi

  mv "$next" "$prev"
  echo "    Promoted frontend-assets-prev for next deploy's asset grace"
}

# ERR-path restore: only when this invocation moved the live grace set aside.
restore_prev_assets_if_promote_started() {
  local root="${1:-/home/deploy}"
  local prev="${root}/frontend-assets-prev"
  local next="${root}/frontend-assets-prev.next"
  local rollback="${root}/frontend-assets-prev.rollback"

  rm -rf "$next" 2>/dev/null || true

  if [[ "${PREV_ASSETS_PROMOTE_STARTED:-0}" == "1" && -d "$rollback" ]]; then
    rm -rf "$prev"
    mv "$rollback" "$prev"
    echo "    Restored frontend-assets-prev from in-progress promote rollback snapshot"
  fi
}

# Unconditional restore used by post-deploy-rollback.sh after a successful
# deploy.sh promote (flag is gone; .rollback is the prior good generation).
restore_prev_assets_from_rollback() {
  local root="${1:-/home/deploy}"
  local prev="${root}/frontend-assets-prev"
  local next="${root}/frontend-assets-prev.next"
  local rollback="${root}/frontend-assets-prev.rollback"

  rm -rf "$next" 2>/dev/null || true

  if [[ -d "$rollback" ]]; then
    rm -rf "$prev"
    mv "$rollback" "$prev"
    echo "    Restored frontend-assets-prev from pre-promotion rollback snapshot"
  fi
}
