#!/usr/bin/env bash
# =============================================================================
# scripts/reclaim-vps-disk.sh
# Free deploy-owned disk before the Deploy 1GB gate.
#
# Safe / idempotent. Never deletes the newest local DB dumps, live app tree,
# or anything outside /home/deploy (+ deploy user caches).
#
# Usage:
#   bash /home/deploy/reclaim-vps-disk.sh
#   bash scripts/reclaim-vps-disk.sh --min-free-kb 1048576
# =============================================================================

set -euo pipefail

MIN_FREE_KB="${MIN_FREE_KB:-1048576}"  # 1 GiB
KEEP_LOCAL_DUMPS="${KEEP_LOCAL_DUMPS:-3}"
LOG_MAX_BYTES="${LOG_MAX_BYTES:-5242880}"  # 5 MiB
BACKUP_DIR="${BACKUP_DIR:-/home/deploy/backups}"
WAL_DIR="${WAL_DIR:-/home/deploy/wal-archive}"
LOG_DIR="${LOG_DIR:-/home/deploy/logs}"
DF_PATH="${DF_PATH:-/home/deploy}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --min-free-kb)
      MIN_FREE_KB="${2:?}"
      shift 2
      ;;
    --keep-local-dumps)
      KEEP_LOCAL_DUMPS="${2:?}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

free_kb() {
  df --output=avail "$DF_PATH" | tail -1 | tr -d ' '
}

human_kb() {
  local kb="$1"
  if command -v numfmt >/dev/null 2>&1; then
    numfmt --to=iec --from-unit=1024 "$kb" 2>/dev/null || echo "${kb}KB"
  else
    echo "${kb}KB"
  fi
}

BEFORE_KB="$(free_kb)"
echo "==> VPS disk reclaim (before: $(human_kb "$BEFORE_KB") free on $DF_PATH)"

# 1) Truncate oversized deploy logs (keep file / permissions).
if [[ -d "$LOG_DIR" ]]; then
  while IFS= read -r -d '' logf; do
    size="$(wc -c < "$logf" | tr -d ' ')"
    if [[ "$size" -gt "$LOG_MAX_BYTES" ]]; then
      : > "$logf" || true
      echo "    truncated log: $logf ($(human_kb $((size / 1024))))"
    fi
  done < <(find "$LOG_DIR" -type f -name '*.log' -print0 2>/dev/null || true)
fi

# 2) Drop leftover SPA swap / staging trees (live dist stays under app/).
for leftover in \
  /home/deploy/frontend-dist-backup-new \
  /home/deploy/frontend-dist
do
  if [[ -e "$leftover" ]]; then
    rm -rf "$leftover"
    echo "    removed leftover: $leftover"
  fi
done

# Keep at most one prior SPA dist backup for rollback.
if [[ -d /home/deploy/frontend-dist-backup ]]; then
  # Only prune nested junk; the backup dir itself is the rollback target.
  find /home/deploy/frontend-dist-backup -type f -name '*.map' -delete 2>/dev/null || true
fi

# 3) Prune old local pg_dump files; keep newest KEEP_LOCAL_DUMPS.
if [[ -d "$BACKUP_DIR" ]]; then
  mapfile -t dumps < <(
    find "$BACKUP_DIR" -maxdepth 1 -type f -name 'backup_*.dump' -printf '%T@ %p\n' 2>/dev/null \
      | sort -nr \
      | awk '{print $2}'
  )
  if [[ "${#dumps[@]}" -gt "$KEEP_LOCAL_DUMPS" ]]; then
    for ((i = KEEP_LOCAL_DUMPS; i < ${#dumps[@]}; i++)); do
      rm -f "${dumps[$i]}"
      echo "    removed old dump: ${dumps[$i]}"
    done
  fi
  # Base backups / stray .dump.gz older than 14d (remote copies should exist).
  find "$BACKUP_DIR" -maxdepth 2 -type f \( -name '*.dump' -o -name '*.dump.gz' -o -name '*.tar' -o -name '*.tar.gz' \) \
    -mtime +14 ! -name 'backup_*.dump' -delete 2>/dev/null || true
fi

# 4) WAL archive: keep 7 days when remote archive is configured; safe local bound.
if [[ -d "$WAL_DIR" ]]; then
  find "$WAL_DIR" -maxdepth 1 -type f -mtime +7 -delete 2>/dev/null || true
  echo "    pruned WAL files older than 7 days in $WAL_DIR"
fi

# 5) User package caches (pip / npm / apt user cache if any).
rm -rf /home/deploy/.cache/pip 2>/dev/null || true
rm -rf /home/deploy/.npm/_cacache 2>/dev/null || true
rm -rf /home/deploy/.cache/typescript 2>/dev/null || true
rm -rf /tmp/npm-* /tmp/pip-* /tmp/frontend-dist* 2>/dev/null || true
echo "    cleared deploy pip/npm caches and /tmp staging"

# 6) Truncate oversized rollback / ops logs in home.
for home_log in /home/deploy/rollback.log /home/deploy/logs/backup.log; do
  if [[ -f "$home_log" ]]; then
    size="$(wc -c < "$home_log" | tr -d ' ')"
    if [[ "$size" -gt "$LOG_MAX_BYTES" ]]; then
      # Keep the last ~200KB of context.
      tail -c 204800 "$home_log" > "${home_log}.tmp.$$" 2>/dev/null \
        && mv -f "${home_log}.tmp.$$" "$home_log" \
        || rm -f "${home_log}.tmp.$$" 2>/dev/null || true
      echo "    rotated oversized: $home_log"
    fi
  fi
done

AFTER_KB="$(free_kb)"
FREED_KB=$((AFTER_KB - BEFORE_KB))
if [[ "$FREED_KB" -lt 0 ]]; then
  FREED_KB=0
fi
echo "    reclaim done: freed ~$(human_kb "$FREED_KB") (now $(human_kb "$AFTER_KB") free)"

if [[ "$AFTER_KB" -lt "$MIN_FREE_KB" ]]; then
  echo "WARNING: still below target $(human_kb "$MIN_FREE_KB") free ($(human_kb "$AFTER_KB") available)" >&2
  echo "    Inspect: du -h --max-depth=1 /home/deploy | sort -h" >&2
  # Non-zero only when used as a hard gate; deploy.sh decides whether to fail.
  exit 0
fi

exit 0
