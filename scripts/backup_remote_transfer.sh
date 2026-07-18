#!/usr/bin/env bash
# backup_remote_transfer.sh — Multi-target off-site upload for backup.sh
# Sourced or invoked with required env already set (from backup.conf + backup.sh).
#
# Required env: BACKUP_DIR FILENAME TIMESTAMP_ISO SIZE_BYTES SHA256 INTEGRITY
#               BACKUP_TYPE LOG_FILE REMOTE_METHOD
# Optional: RCLONE_TARGETS RCLONE_REMOTE RCLONE_BUCKET RCLONE_PATH_PREFIX
#           REMOTE_UPLOAD_HOUR_UTC REMOTE_RETENTION_DAYS REMOTE_* timeouts
#
# Sets: REMOTE_TRANSFERRED REMOTE_PATH BACKUP_FAILED (may set to 1)
# Expects send_alert function if alerting is desired (optional).

set -euo pipefail

REMOTE_TRANSFERRED="${REMOTE_TRANSFERRED:-false}"
REMOTE_PATH="${REMOTE_PATH:-}"
BACKUP_FAILED="${BACKUP_FAILED:-0}"

resolve_rclone_targets() {
    if [[ -n "${RCLONE_TARGETS:-}" ]]; then
        echo "$RCLONE_TARGETS"
        return 0
    fi
    if [[ -n "${RCLONE_REMOTE:-}" && -n "${RCLONE_BUCKET:-}" ]]; then
        echo "${RCLONE_REMOTE}:${RCLONE_BUCKET}"
        return 0
    fi
    return 1
}

prune_remote_prefix() {
    local remote_name="$1"
    local bucket_name="$2"
    local retention="${REMOTE_RETENTION_DAYS:-14}"
    local prefix="${RCLONE_PATH_PREFIX:-backups}"
    local dest="${remote_name}:${bucket_name}/${prefix}/"
    case "$remote_name" in
        b2*)
            rclone delete --min-age "${retention}d" --b2-hard-delete "$dest" 2>>"$LOG_FILE" || true
            ;;
        *)
            rclone delete --min-age "${retention}d" "$dest" 2>>"$LOG_FILE" || true
            ;;
    esac
}

transfer_one_target() {
    local remote_name="$1"
    local bucket_name="$2"
    local object_path="$3"
    local retry_max="${4:-${REMOTE_RETRY_COUNT:-3}}"
    local retry_delay="${REMOTE_RETRY_DELAY:-300}"
    local attempt=0
    local dest="${remote_name}:${bucket_name}/${object_path}"

    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: pre-transfer prune - ${remote_name}:${bucket_name} (retain ${REMOTE_RETENTION_DAYS:-14}d)" >> "$LOG_FILE"
    prune_remote_prefix "$remote_name" "$bucket_name"

    while [[ "$attempt" -lt "$retry_max" ]]; do
        attempt=$(( attempt + 1 ))
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: transfer ${remote_name}:${bucket_name} attempt $attempt/$retry_max" >> "$LOG_FILE"
        local transfer_exit=0
        rclone copyto "$BACKUP_DIR/$FILENAME" "$dest" \
            --contimeout "${REMOTE_CONNECT_TIMEOUT:-30}s" \
            2>>"$LOG_FILE" || transfer_exit=$?
        if [[ "$transfer_exit" -ne 0 ]]; then
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: rclone copy failed for ${remote_name} attempt $attempt (exit $transfer_exit)" >> "$LOG_FILE"
            if [[ "$attempt" -lt "$retry_max" ]]; then
                sleep "$retry_delay"
            fi
            continue
        fi
        local local_size remote_size_json remote_size
        local_size="$(stat -c "%s" "$BACKUP_DIR/$FILENAME")"
        remote_size_json="$(rclone size "$dest" --json 2>>"$LOG_FILE")" || {
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: rclone size check failed for ${remote_name} attempt $attempt" >> "$LOG_FILE"
            if [[ "$attempt" -lt "$retry_max" ]]; then
                sleep "$retry_delay"
            fi
            continue
        }
        remote_size="$(printf '%s' "$remote_size_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("bytes", -1))')"
        if [[ "$remote_size" -eq "$local_size" ]]; then
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: transfer verified - ${remote_name}:${bucket_name}/${object_path} (${local_size}B)" >> "$LOG_FILE"
            prune_remote_prefix "$remote_name" "$bucket_name"
            return 0
        fi
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: size mismatch ${remote_name} attempt $attempt - local=${local_size}B remote=${remote_size}B" >> "$LOG_FILE"
        if [[ "$attempt" -lt "$retry_max" ]]; then
            sleep "$retry_delay"
        fi
    done
    prune_remote_prefix "$remote_name" "$bucket_name"
    return 1
}

recent_cloud_transfer_exists() {
    BACKUP_DIR="$BACKUP_DIR" python3 - <<'PY'
import json, os, sys
from datetime import datetime, timezone, timedelta
manifest = os.path.join(os.environ["BACKUP_DIR"], "backup_manifest.log")
cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
try:
    lines = [ln.strip() for ln in open(manifest, encoding="utf-8") if ln.strip()]
except OSError:
    sys.exit(1)
for line in reversed(lines):
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue
    if entry.get("integrity") != "valid":
        continue
    transferred = entry.get("remote_transferred")
    if transferred is not True and transferred != "true":
        continue
    ts = entry.get("timestamp", "")
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except ValueError:
        continue
    if when >= cutoff:
        sys.exit(0)
sys.exit(1)
PY
}

append_manifest_remote_status() {
    _BF_FILENAME="$FILENAME" \
    _BF_TIMESTAMP="$TIMESTAMP_ISO" \
    _BF_SIZE="$SIZE_BYTES" \
    _BF_SHA256="$SHA256" \
    _BF_INTEGRITY="$INTEGRITY" \
    _BF_TYPE="$BACKUP_TYPE" \
    _BF_REMOTE_TRANSFERRED="$1" \
    _BF_REMOTE_PATH="$2" \
    python3 - <<'PY'
import json, os
print(json.dumps({
    "filename": os.environ["_BF_FILENAME"],
    "timestamp": os.environ["_BF_TIMESTAMP"],
    "size_bytes": int(os.environ["_BF_SIZE"]),
    "sha256": os.environ["_BF_SHA256"],
    "integrity": os.environ["_BF_INTEGRITY"],
    "type": os.environ["_BF_TYPE"],
    "remote_transferred": os.environ["_BF_REMOTE_TRANSFERRED"] == "True",
    "remote_path": os.environ.get("_BF_REMOTE_PATH", ""),
}))
PY
}

if [[ -z "${REMOTE_METHOD:-}" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: REMOTE_METHOD not set - skipping remote transfer (local backup only)" >> "$LOG_FILE"
    return 0 2>/dev/null || exit 0
fi

DISPATCH_CHECK=0
REMOTE_METHOD="$REMOTE_METHOD" python3 - <<'PY' 2>>"$LOG_FILE" || DISPATCH_CHECK=$?
import os, sys
sys.path.insert(0, "/home/deploy")
from backup_lib import dispatch_transfer_method
try:
    dispatch_transfer_method(os.environ["REMOTE_METHOD"])
except ValueError as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
PY

if [[ "$DISPATCH_CHECK" -ne 0 ]]; then
    BACKUP_FAILED=1
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Invalid REMOTE_METHOD - skipping remote transfer" >> "$LOG_FILE"
    if declare -F send_alert >/dev/null 2>&1; then
        send_alert \
            "Remote transfer skipped - invalid REMOTE_METHOD [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
            "REMOTE_METHOD is not a valid transfer method. Remote transfer was skipped. Backup type: $BACKUP_TYPE."
    fi
    return 0 2>/dev/null || exit 0
fi

SKIP_REMOTE=0
UPLOAD_HOUR="${REMOTE_UPLOAD_HOUR_UTC:-10}"
CURRENT_HOUR="$(date -u +%H)"
CURRENT_HOUR=$((10#$CURRENT_HOUR))

if [[ "$BACKUP_TYPE" == "scheduled" ]]; then
    if [[ "$CURRENT_HOUR" -ne "$UPLOAD_HOUR" ]]; then
        SKIP_REMOTE=1
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: scheduled run outside REMOTE_UPLOAD_HOUR_UTC=${UPLOAD_HOUR} (now=${CURRENT_HOUR}) - local only" >> "$LOG_FILE"
    fi
elif [[ "$BACKUP_TYPE" == "pre-deploy" ]]; then
    if recent_cloud_transfer_exists; then
        SKIP_REMOTE=1
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: pre-deploy - recent cloud transfer within 24h - skipping remote upload" >> "$LOG_FILE"
    fi
fi

if [[ "$SKIP_REMOTE" -ne 0 ]]; then
    return 0 2>/dev/null || exit 0
fi

TARGETS_STR="$(resolve_rclone_targets)" || TARGETS_STR=""
if [[ -z "$TARGETS_STR" ]]; then
    BACKUP_FAILED=1
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: no RCLONE_TARGETS or RCLONE_REMOTE/RCLONE_BUCKET configured" >> "$LOG_FILE"
    if declare -F send_alert >/dev/null 2>&1; then
        send_alert \
            "Remote transfer skipped - no targets [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
            "REMOTE_METHOD is set but no rclone targets are configured. Backup type: $BACKUP_TYPE."
    fi
    return 0 2>/dev/null || exit 0
fi

OBJECT_PATH="$(python3 /home/deploy/backup_lib.py generate-remote-path "${RCLONE_PATH_PREFIX:-backups}" "$TIMESTAMP_ISO" "$FILENAME")"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: remote object path=$OBJECT_PATH targets=$TARGETS_STR" >> "$LOG_FILE"

SUCCESS_PATHS=()
FAILED_TARGETS=()
# shellcheck disable=SC2206
TARGET_ARR=($TARGETS_STR)
PRIMARY_RETRY="${REMOTE_RETRY_COUNT:-3}"
for target in "${TARGET_ARR[@]}"; do
    remote_name="${target%%:*}"
    bucket_name="${target#*:}"
    if [[ -z "$remote_name" || -z "$bucket_name" || "$remote_name" == "$target" ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: invalid RCLONE_TARGETS entry [$target] (expected remote:bucket)" >> "$LOG_FILE"
        FAILED_TARGETS+=("$target")
        continue
    fi
    # After one off-site copy succeeds, cap further retries so a bad secondary
    # provider cannot hang the backup for REMOTE_RETRY_COUNT * DELAY.
    target_retries="$PRIMARY_RETRY"
    if [[ "${#SUCCESS_PATHS[@]}" -gt 0 ]]; then
        target_retries=1
    fi
    if transfer_one_target "$remote_name" "$bucket_name" "$OBJECT_PATH" "$target_retries"; then
        SUCCESS_PATHS+=("${remote_name}:${bucket_name}/${OBJECT_PATH}")
    else
        FAILED_TARGETS+=("${remote_name}:${bucket_name}")
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: remote transfer failed for ${remote_name}:${bucket_name}" >> "$LOG_FILE"
    fi
done

if [[ "${#SUCCESS_PATHS[@]}" -gt 0 ]]; then
    REMOTE_TRANSFERRED="true"
    REMOTE_PATH=$(printf '%s;' "${SUCCESS_PATHS[@]}")
    REMOTE_PATH="${REMOTE_PATH%;}"
else
    REMOTE_TRANSFERRED="false"
    REMOTE_PATH=""
fi

if [[ "${#FAILED_TARGETS[@]}" -gt 0 ]]; then
    SUCCESS_LIST="none"
    if [[ "${#SUCCESS_PATHS[@]}" -gt 0 ]]; then
        SUCCESS_LIST="${SUCCESS_PATHS[*]}"
    fi
    # Fail the backup run only when every configured target failed.
    # Partial success must not block deploy (local dump + at least one off-site copy is enough).
    if [[ "${#SUCCESS_PATHS[@]}" -eq 0 ]]; then
        BACKUP_FAILED=1
    fi
    if declare -F send_alert >/dev/null 2>&1; then
        send_alert \
            "Remote transfer FAILED for some targets [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
            "Failed targets: ${FAILED_TARGETS[*]}. Succeeded: ${SUCCESS_LIST}. File: $FILENAME. Check $LOG_FILE."
    fi
fi

if [[ "$REMOTE_TRANSFERRED" == "true" ]]; then
    REMOTE_TRANSFERRED_PYTHON="True"
else
    REMOTE_TRANSFERRED_PYTHON="False"
fi

append_manifest_remote_status "$REMOTE_TRANSFERRED_PYTHON" "$REMOTE_PATH" \
    | python3 /home/deploy/backup_lib.py serialize-manifest >> "$BACKUP_DIR/backup_manifest.log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: manifest updated with remote transfer status (transferred=$REMOTE_TRANSFERRED)" >> "$LOG_FILE"
