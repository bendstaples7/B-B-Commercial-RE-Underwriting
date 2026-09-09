#!/usr/bin/env bash
# Smoke test for scripts/reclaim-vps-disk.sh (temp fake VPS home).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/reclaim-vps-disk.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/home/deploy/backups" "$TMP/home/deploy/logs" "$TMP/home/deploy/wal-archive"
# Fake dumps: 5 files, keep newest 3 (write then backdate so mtime sticks)
for i in 1 2 3 4 5; do
  echo "dump$i" > "$TMP/home/deploy/backups/backup_2026010${i}.dump"
  touch -d "2026-01-0${i} 12:00:00" "$TMP/home/deploy/backups/backup_2026010${i}.dump"
done
# Oversized log
python3 - <<PY
from pathlib import Path
p = Path("$TMP/home/deploy/logs/backup.log")
p.write_bytes(b"x" * (6 * 1024 * 1024))
PY
mkdir -p "$TMP/home/deploy/frontend-dist-backup-new"
echo junk > "$TMP/home/deploy/frontend-dist-backup-new/x"
# Old WAL (write first, then backdate mtime — echo after touch resets mtime)
echo wal > "$TMP/home/deploy/wal-archive/old.wal"
touch -d "2026-01-01 12:00:00" "$TMP/home/deploy/wal-archive/old.wal"
echo new > "$TMP/home/deploy/wal-archive/new.wal"

# Point script paths via env overrides by running a wrapper that cds... 
# Script hardcodes /home/deploy — exercise via bind or sed copy.
WORK="$TMP/work"
mkdir -p "$WORK"
sed \
  -e "s|/home/deploy|$TMP/home/deploy|g" \
  "$SCRIPT" > "$WORK/reclaim.sh"
chmod +x "$WORK/reclaim.sh"

# df path: use TMP so free space check is meaningful on this runner
DF_PATH="$TMP" BACKUP_DIR="$TMP/home/deploy/backups" \
  WAL_DIR="$TMP/home/deploy/wal-archive" LOG_DIR="$TMP/home/deploy/logs" \
  bash "$WORK/reclaim.sh" --min-free-kb 1 --keep-local-dumps 3

remaining="$(find "$TMP/home/deploy/backups" -name 'backup_*.dump' | wc -l | tr -d ' ')"
test "$remaining" = "3" || { echo "expected 3 dumps, got $remaining"; exit 1; }
test ! -e "$TMP/home/deploy/frontend-dist-backup-new" || { echo "leftover frontend-dist-backup-new"; exit 1; }
log_size="$(wc -c < "$TMP/home/deploy/logs/backup.log" | tr -d ' ')"
test "$log_size" -lt 6000000 || { echo "log not truncated: $log_size"; exit 1; }
test ! -e "$TMP/home/deploy/wal-archive/old.wal" || { echo "old wal not pruned"; exit 1; }
test -e "$TMP/home/deploy/wal-archive/new.wal" || { echo "new wal missing"; exit 1; }

echo "reclaim-vps-disk smoke OK"
