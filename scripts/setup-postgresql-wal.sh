#!/usr/bin/env bash
set -euo pipefail

# setup-postgresql-wal.sh
# Configures PostgreSQL WAL archiving and passwordless peer auth for the deploy user.
# Run as a user with sudo privileges on the VPS.
#
# Requirements: 1.7, 5.1, 5.2

STEP_OK="[OK]"
STEP_FAIL="[FAIL]"
STEP_SKIP="[SKIP]"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

pass() {
    echo "$STEP_OK $*"
}

fail() {
    echo "$STEP_FAIL $*" >&2
    exit 1
}

skip() {
    echo "$STEP_SKIP $*"
}

# ── Step 1: Detect PostgreSQL version ─────────────────────────────────────────
log "Step 1: Detecting PostgreSQL version..."
PG_VERSION=$(psql --version | grep -oP '\d+' | head -1)
if [[ -z "$PG_VERSION" ]]; then
    fail "Could not detect PostgreSQL version. Is psql installed and on PATH?"
fi
PG_CONF="/etc/postgresql/$PG_VERSION/main/postgresql.conf"
PG_HBA="/etc/postgresql/$PG_VERSION/main/pg_hba.conf"
pass "Detected PostgreSQL version: $PG_VERSION"
log "  postgresql.conf: $PG_CONF"
log "  pg_hba.conf:     $PG_HBA"

# ── Step 2: Add WAL archiving settings to postgresql.conf ─────────────────────
log "Step 2: Configuring WAL archiving in postgresql.conf..."
if [[ ! -f "$PG_CONF" ]]; then
    fail "postgresql.conf not found at $PG_CONF"
fi

if grep -q "archive_mode" "$PG_CONF"; then
    skip "WAL archiving settings already present in $PG_CONF — skipping."
else
    log "  Appending WAL archiving settings..."
    sudo tee -a "$PG_CONF" > /dev/null <<'EOF'

# ── WAL archiving (added by setup-postgresql-wal.sh) ─────────────────────────
wal_level = replica
archive_mode = on
archive_command = '/home/deploy/wal-archive.sh %p %f'
archive_timeout = 300
EOF
    pass "WAL archiving settings appended to $PG_CONF"
fi

# ── Step 3: Reload PostgreSQL after postgresql.conf change ────────────────────
log "Step 3: Reloading PostgreSQL (after postgresql.conf change)..."
if sudo systemctl reload postgresql; then
    pass "PostgreSQL reloaded successfully."
else
    fail "Failed to reload PostgreSQL. Check 'journalctl -u postgresql' for details."
fi

# ── Step 4: Configure passwordless peer auth in pg_hba.conf ──────────────────
log "Step 4: Configuring passwordless peer auth in pg_hba.conf..."
if [[ ! -f "$PG_HBA" ]]; then
    fail "pg_hba.conf not found at $PG_HBA"
fi

PEER_ENTRY="local   real_estate_analysis   deploy   peer"
if grep -qF "$PEER_ENTRY" "$PG_HBA"; then
    skip "Peer auth entry already present in $PG_HBA — skipping."
else
    log "  Inserting peer auth entry before the first 'local' line..."
    # Insert the peer entry before the first existing 'local' line so it takes
    # precedence over any broader local rules (e.g. 'local all all peer').
    sudo sed -i "0,/^local/{s|^local|${PEER_ENTRY}\nlocal|}" "$PG_HBA"
    pass "Peer auth entry added to $PG_HBA"
fi

# ── Step 5: Reload PostgreSQL after pg_hba.conf change ───────────────────────
log "Step 5: Reloading PostgreSQL (after pg_hba.conf change)..."
if sudo systemctl reload postgresql; then
    pass "PostgreSQL reloaded successfully."
else
    fail "Failed to reload PostgreSQL. Check 'journalctl -u postgresql' for details."
fi

# ── Step 6: Verify passwordless pg_dump works ────────────────────────────────
log "Step 6: Verifying passwordless pg_dump as deploy user..."
TEST_DUMP="/tmp/test_auth_$$.dump"
if sudo -u deploy pg_dump -Fc -d real_estate_analysis -f "$TEST_DUMP"; then
    rm -f "$TEST_DUMP"
    pass "pg_dump succeeded without a password prompt."
else
    rm -f "$TEST_DUMP" 2>/dev/null || true
    fail "pg_dump failed. Check pg_hba.conf peer auth entry and that the 'deploy' PostgreSQL role exists."
fi

# ── Step 7: Verify WAL archiving is active ────────────────────────────────────
log "Step 7: Verifying WAL archiving is active..."
ARCHIVE_MODE=$(sudo -u deploy psql -d real_estate_analysis -tAc "SHOW archive_mode;" 2>/dev/null | tr -d '[:space:]')
if [[ "$ARCHIVE_MODE" == "on" ]]; then
    pass "archive_mode = on — WAL archiving is active."
else
    fail "archive_mode is '$ARCHIVE_MODE' (expected 'on'). A full PostgreSQL restart (not just reload) may be required for wal_level/archive_mode changes to take effect: sudo systemctl restart postgresql"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
log "============================================================"
log "setup-postgresql-wal.sh completed successfully."
log ""
log "Next steps:"
log "  1. Verify a WAL segment appears after a manual switch:"
log "       sudo -u deploy psql -d real_estate_analysis -c 'SELECT pg_switch_wal();'"
log "       ls -lh /home/deploy/wal-archive/"
log "  2. Confirm wal-archive.sh is executable:"
log "       ls -la /home/deploy/wal-archive.sh"
log "  3. Review /home/deploy/logs/backup.log for any archive errors."
log "============================================================"
