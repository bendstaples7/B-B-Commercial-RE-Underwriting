#!/usr/bin/env bash
# setup-cron.sh — Install the 5 required cron entries for the deploy user
#
# Usage:
#   sudo bash setup-cron.sh          # run as root (uses crontab -u deploy)
#   bash setup-cron.sh               # run as the deploy user directly
#
# Requirements: 1.1, 2.1, 5.3, 7.3

set -euo pipefail

# ── Permission check ──────────────────────────────────────────────────────────
# crontab -u deploy requires root (or the deploy user itself)
CURRENT_USER="$(id -un)"
if [[ "$CURRENT_USER" != "root" && "$CURRENT_USER" != "deploy" ]]; then
    echo "ERROR: This script must be run as root or as the deploy user." >&2
    echo "       Current user: $CURRENT_USER" >&2
    echo "       Run: sudo bash setup-cron.sh" >&2
    exit 1
fi

# ── Determine crontab command ─────────────────────────────────────────────────
if [[ "$CURRENT_USER" == "root" ]]; then
    CRONTAB_READ="crontab -u deploy -l"
    CRONTAB_INSTALL="crontab -u deploy"
    CRONTAB_LIST="crontab -u deploy -l"
else
    # Running as deploy user — no -u flag needed
    CRONTAB_READ="crontab -l"
    CRONTAB_INSTALL="crontab"
    CRONTAB_LIST="crontab -l"
fi

TMPFILE="$(mktemp /tmp/deploy_crontab.XXXXXX)"
trap 'rm -f "$TMPFILE" "${TMPFILE_NEW:-}" "${ERRTMP:-}"' EXIT

# ── Load existing crontab (tolerate "no crontab for" error only) ──────────────
ERRTMP="$(mktemp /tmp/crontab_err.XXXXXX)"
$CRONTAB_READ 2>"$ERRTMP" > "$TMPFILE" || {
    if grep -q "no crontab for" "$ERRTMP" 2>/dev/null; then
        : # empty crontab is fine
    else
        cat "$ERRTMP" >&2
        rm -f "$ERRTMP"
        exit 1
    fi
}
rm -f "$ERRTMP"

echo "==> Current crontab loaded ($(wc -l < "$TMPFILE") lines)"

# ── Ensure MAILTO="" is present (suppress duplicate email delivery) ───────────
if ! grep -qF 'MAILTO=""' "$TMPFILE"; then
    # Prepend MAILTO at the top of the file
    TMPFILE_NEW="$(mktemp /tmp/deploy_crontab.XXXXXX)"
    echo 'MAILTO=""' | cat - "$TMPFILE" > "$TMPFILE_NEW" && mv "$TMPFILE_NEW" "$TMPFILE"
    echo "==> Added MAILTO=\"\" to suppress duplicate email delivery"
else
    echo "==> MAILTO=\"\" already present — skipping"
fi

# ── Define the 5 required cron entries ───────────────────────────────────────
declare -a CRON_ENTRIES=(
    "0  2 * * *  /home/deploy/backup.sh >> /home/deploy/logs/backup.log 2>&1"
    "0 10 * * *  /home/deploy/backup.sh >> /home/deploy/logs/backup.log 2>&1"
    "0 18 * * *  /home/deploy/backup.sh >> /home/deploy/logs/backup.log 2>&1"
    "0  1 * * 0  /home/deploy/pg-basebackup.sh >> /home/deploy/logs/backup.log 2>&1"
    "30 0 * * *  /home/deploy/daily-summary.sh >> /home/deploy/logs/backup.log 2>&1"
)

# Grep patterns to detect each entry (script path is the unique identifier)
declare -a GREP_PATTERNS=(
    "backup\.sh.*02:00\|0  2 \* \* \*.*backup\.sh\|0 2 \* \* \*.*backup\.sh"
    "backup\.sh.*10:00\|0 10 \* \* \*.*backup\.sh"
    "backup\.sh.*18:00\|0 18 \* \* \*.*backup\.sh"
    "pg-basebackup\.sh"
    "daily-summary\.sh"
)

declare -a ENTRY_LABELS=(
    "backup.sh at 02:00 UTC"
    "backup.sh at 10:00 UTC"
    "backup.sh at 18:00 UTC"
    "pg-basebackup.sh at Sunday 01:00 UTC"
    "daily-summary.sh at 00:30 UTC"
)

# ── Add each entry if not already present ────────────────────────────────────
ADDED=0
for i in "${!CRON_ENTRIES[@]}"; do
    ENTRY="${CRON_ENTRIES[$i]}"
    PATTERN="${GREP_PATTERNS[$i]}"
    LABEL="${ENTRY_LABELS[$i]}"

    if grep -qE "$PATTERN" "$TMPFILE" 2>/dev/null; then
        echo "==> Already present — skipping: $LABEL"
    else
        echo "$ENTRY" >> "$TMPFILE"
        echo "==> Added: $LABEL"
        ADDED=$((ADDED + 1))
    fi
done

# ── Install the updated crontab ───────────────────────────────────────────────
$CRONTAB_INSTALL "$TMPFILE"
echo ""
echo "==> Crontab installed ($ADDED new entries added)"

# ── Verify all 5 entries are present ─────────────────────────────────────────
echo ""
echo "==> Verifying installed crontab:"
INSTALLED_CRONTAB="$($CRONTAB_LIST 2>/dev/null)"
echo "$INSTALLED_CRONTAB"

echo ""
echo "==> Verification checks:"
MISSING=0

check_entry() {
    local pattern="$1"
    local label="$2"
    if echo "$INSTALLED_CRONTAB" | grep -qE "$pattern"; then
        echo "    [OK] $label"
    else
        echo "    [MISSING] $label" >&2
        MISSING=$((MISSING + 1))
    fi
}

check_entry "0[[:space:]]+2[[:space:]]+\*[[:space:]]+\*[[:space:]]+\*.*backup\.sh"   "backup.sh at 02:00 UTC"
check_entry "0[[:space:]]+10[[:space:]]+\*[[:space:]]+\*[[:space:]]+\*.*backup\.sh"  "backup.sh at 10:00 UTC"
check_entry "0[[:space:]]+18[[:space:]]+\*[[:space:]]+\*[[:space:]]+\*.*backup\.sh"  "backup.sh at 18:00 UTC"
check_entry "0[[:space:]]+1[[:space:]]+\*[[:space:]]+\*[[:space:]]+0.*pg-basebackup\.sh" "pg-basebackup.sh at Sunday 01:00 UTC"
check_entry "30[[:space:]]+0[[:space:]]+\*[[:space:]]+\*[[:space:]]+\*.*daily-summary\.sh" "daily-summary.sh at 00:30 UTC"

# ── Final result ──────────────────────────────────────────────────────────────
echo ""
if [[ "$MISSING" -eq 0 ]]; then
    echo "SUCCESS: All 5 cron entries are installed for the deploy user."
else
    echo "ERROR: $MISSING cron entry/entries are missing after installation." >&2
    exit 1
fi
