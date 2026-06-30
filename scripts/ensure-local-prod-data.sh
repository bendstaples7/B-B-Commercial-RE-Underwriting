#!/usr/bin/env bash
# ensure-local-prod-data.sh — Ensures local PostgreSQL has production lead data.
# Called automatically by python dev.py. No manual steps required.
#
# Install daily background sync (optional):
#   bash scripts/ensure-local-prod-data.sh --install

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT}/backend"
ENV_FILE="${ROOT}/.env"
DUMP_DIR="${HOME}/.local/share/bbanalyzer/dumps"
CACHED_DUMP="${DUMP_DIR}/prod_dump.dump"
LOG_DIR="${HOME}/.local/share/bbanalyzer/logs"
LOG_FILE="${LOG_DIR}/ensure-local-prod-data.log"
MIN_LEADS=1000
MIN_DUMP_BYTES=10240
WORKFLOW="download-prod-dump.yml"
DEFAULT_REPO="bendstaples7/B-B-Commercial-RE-Underwriting"

mkdir -p "$DUMP_DIR" "$LOG_DIR"

log() {
    local ts
    ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "[$ts] $*"
    echo "[$ts] $*" >> "$LOG_FILE"
}

die() {
    log "ERROR: $*"
    exit 1
}

if [[ "${1:-}" == "--install" ]]; then
    SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
    CRON_LINE="0 3 * * * /bin/bash ${SCRIPT_PATH} >> ${LOG_FILE} 2>&1"
  if crontab -l 2>/dev/null | grep -Fq "ensure-local-prod-data.sh"; then
        echo "Cron entry already installed."
    else
        (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
        echo "Installed daily cron at 03:00: $CRON_LINE"
    fi
    exit 0
fi

if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE" 2>/dev/null || true
fi

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/real_estate_analysis}"

get_lead_count() {
    local count
    count="$(psql "$DB_URL" -tAc "SELECT count(*) FROM leads;" 2>/dev/null || echo "ERROR")"
    if [[ "$count" == "ERROR" ]]; then
        die "Could not query leads — is PostgreSQL running?"
    fi
    echo "$count"
}

valid_dump() {
    [[ -f "$1" ]] && [[ "$(wc -c < "$1" | tr -d ' ')" -ge "$MIN_DUMP_BYTES" ]]
}

restore_dump() {
    log "Restoring from $1 ..."
    pg_restore --clean --if-exists -d "$DB_URL" "$1" || die "pg_restore failed"
    (cd "$BACKEND_DIR" && flask db upgrade) || die "flask db upgrade failed"
}

resolve_github_repo() {
    local url
    url="$(git -C "$ROOT" remote get-url origin 2>/dev/null || true)"
    if [[ "$url" =~ github\.com[:/]([^/]+/[^/.]+) ]]; then
        echo "${BASH_REMATCH[1]%.git}"
    else
        echo "$DEFAULT_REPO"
    fi
}

gh_ready() {
    command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1
}

gh_fetch_dump() {
    local repo="$1"
    gh_ready || { log "GitHub CLI not authenticated — run: gh auth login"; return 1; }

    local run_id created
  while IFS=$'\t' read -r run_id created; do
        [[ -z "$run_id" ]] && continue
        local age_days
        age_days=$(( ($(date +%s) - $(date -d "$created" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$created" +%s)) / 86400 ))
        if [[ "$age_days" -le 7 ]]; then
            log "Downloading prod dump from Actions run $run_id ..."
            rm -f "$CACHED_DUMP"
            gh run download "$run_id" -R "$repo" -n prod-dump -D "$DUMP_DIR"
            valid_dump "$CACHED_DUMP" && return 0
        fi
    done < <(gh run list --workflow="$WORKFLOW" -R "$repo" --status=success --limit=5 \
        --json databaseId,createdAt -q '.[] | [.databaseId, .createdAt] | @tsv' 2>/dev/null || true)

    log "Triggering $WORKFLOW on main ..."
    gh workflow run "$WORKFLOW" --ref main -R "$repo"
    sleep 15
    run_id="$(gh run list --workflow="$WORKFLOW" -R "$repo" --limit=1 --json databaseId -q '.[0].databaseId')"
    [[ -n "$run_id" ]] || return 1
    gh run watch "$run_id" -R "$repo" --exit-status
    rm -f "$CACHED_DUMP"
    gh run download "$run_id" -R "$repo" -n prod-dump -D "$DUMP_DIR"
    valid_dump "$CACHED_DUMP"
}

log "=== ensure local prod data ==="

LEAD_COUNT="$(get_lead_count)"
if [[ "$LEAD_COUNT" -ge "$MIN_LEADS" ]]; then
    log "Data ready: $LEAD_COUNT leads"
    exit 0
fi

log "Only $LEAD_COUNT leads — auto-restoring ..."

if valid_dump "$CACHED_DUMP"; then
    restore_dump "$CACHED_DUMP"
    LEAD_COUNT="$(get_lead_count)"
    if [[ "$LEAD_COUNT" -ge "$MIN_LEADS" ]]; then
        log "Restore complete: $LEAD_COUNT leads"
        exit 0
    fi
fi

REPO="$(resolve_github_repo)"
if gh_fetch_dump "$REPO"; then
    restore_dump "$CACHED_DUMP"
    LEAD_COUNT="$(get_lead_count)"
    if [[ "$LEAD_COUNT" -ge "$MIN_LEADS" ]]; then
        log "Restore complete: $LEAD_COUNT leads"
        exit 0
    fi
fi

if [[ -f "${HOME}/prod_for_dev.dump" ]] && valid_dump "${HOME}/prod_for_dev.dump"; then
    restore_dump "${HOME}/prod_for_dev.dump"
    LEAD_COUNT="$(get_lead_count)"
    [[ "$LEAD_COUNT" -ge "$MIN_LEADS" ]] && exit 0
fi

die "Automatic production data restore failed. Run: gh auth login. Logs: $LOG_FILE"
