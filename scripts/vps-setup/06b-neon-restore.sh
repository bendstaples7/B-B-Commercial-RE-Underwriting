#!/usr/bin/env bash
# =============================================================================
# 06b-neon-restore.sh
# VPS Setup — Task 2.2 (Part B): Restore Neon dump to local PostgreSQL.
#
# Requirements: 2.4, 2.6
#
# Run ON THE VPS as the deploy user (NOT as root):
#   bash /home/deploy/06b-neon-restore.sh
#
# Prerequisites:
#   - 05-postgres-setup.sh has been run (app_user role and real_estate_analysis
#     database exist)
#   - 06a-neon-export.sh has been run (neon_export.dump is in /home/deploy/)
#   - The deploy user can connect to PostgreSQL as app_user
#
# Non-fatal pg_restore errors (Requirement 2.6):
#   The following error classes are EXPECTED and ACCEPTABLE when restoring a
#   Neon dump to a fresh PostgreSQL instance.  They do NOT indicate data loss:
#
#   1. "ERROR: role "neon_superuser" does not exist"
#      Neon creates an internal superuser role that does not exist on the VPS.
#      --no-owner and --no-acl suppress most of these, but some may slip through
#      in SECURITY LABEL or COMMENT statements.
#
#   2. "ERROR: role "neondb_owner" does not exist" (or similar Neon-internal roles)
#      Same as above — Neon-specific roles that have no equivalent on the VPS.
#
#   3. "ERROR: duplicate key value violates unique constraint" on Alembic tables
#      Occurs when idempotent migrations (IF NOT EXISTS) have already inserted
#      rows into alembic_version.  Harmless — the schema is already correct.
#
#   4. "ERROR: relation "..." already exists"
#      Occurs when the database already has tables from a previous restore attempt.
#      Re-running this script drops and recreates the database to avoid this.
#
#   5. "pg_restore: warning: errors ignored on restore: N"
#      pg_restore exits non-zero when any error occurs, even non-fatal ones.
#      This script captures the exit code and inspects the error log to
#      distinguish fatal errors from the acceptable ones listed above.
#
# This script is IDEMPOTENT — it drops and recreates the database before
# restoring, so re-running it produces a clean, consistent state.
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { error "$*"; exit 1; }

# ── Configuration ─────────────────────────────────────────────────────────────
DEPLOY_USER="${SUDO_USER:-${USER:-deploy}}"
DUMP_FILE="/home/${DEPLOY_USER}/neon_export.dump"
DB_NAME="real_estate_analysis"
DB_USER="app_user"
DB_HOST="localhost"
LOG_FILE="/home/${DEPLOY_USER}/pg_restore_errors.log"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ── Verify running as deploy user (not root) ──────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    die "Run this script as the deploy user, NOT as root."
fi

# ── Verify dump file exists ───────────────────────────────────────────────────
if [[ ! -f "${DUMP_FILE}" ]]; then
    die "Dump file not found: ${DUMP_FILE}
  Run 06a-neon-export.sh on your local machine first, then scp the dump here."
fi

DUMP_SIZE=$(du -sh "${DUMP_FILE}" | cut -f1)

echo ""
echo "============================================================"
echo "  Task 2.2 (Part B) — Neon Restore"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Dump file:  ${DUMP_FILE} (${DUMP_SIZE})"
echo "  Database:   ${DB_NAME}"
echo "  DB user:    ${DB_USER}"
echo "  DB host:    ${DB_HOST}"
echo "  Error log:  ${LOG_FILE}"
echo "============================================================"
echo ""

# =============================================================================
# Step 1: Verify PostgreSQL is running and app_user exists
# =============================================================================
info "Step 1: Verifying PostgreSQL service and app_user role..."

if ! systemctl is-active --quiet postgresql; then
    die "PostgreSQL is not running. Start it with: sudo systemctl start postgresql"
fi
info "  ✓ PostgreSQL service is active."

ROLE_EXISTS=$(sudo -u postgres psql -tAc \
    "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}';" 2>/dev/null || echo "")
if [[ "$ROLE_EXISTS" != "1" ]]; then
    die "PostgreSQL role '${DB_USER}' does not exist.
  Run 05-postgres-setup.sh first to create the role and database."
fi
info "  ✓ Role '${DB_USER}' exists."

# =============================================================================
# Step 2: Drop and recreate the database (idempotent clean slate)
# =============================================================================
info "Step 2: Dropping and recreating '${DB_NAME}' for a clean restore..."
warn "  This will DELETE all existing data in '${DB_NAME}'."
warn "  Press Ctrl+C within 5 seconds to abort..."
sleep 5

# Terminate any active connections before dropping
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();
SQL

sudo -u postgres psql -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS ${DB_NAME};"
sudo -u postgres psql -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

# Re-grant schema privileges (needed after recreating the database)
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<SQL
GRANT ALL PRIVILEGES ON SCHEMA public TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${DB_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ${DB_USER};
SQL

info "  ✓ Database '${DB_NAME}' recreated and privileges granted."

# =============================================================================
# Step 3: Run pg_restore
# =============================================================================
info "Step 3: Running pg_restore..."
info "  Flags: --no-owner --no-acl --dbname=${DB_NAME} --username=${DB_USER} --host=${DB_HOST}"
info "  (This may take several minutes for large databases...)"

# Clear previous error log
> "${LOG_FILE}"

# pg_restore flags:
#   --no-owner  : do not set object ownership (Neon owners don't exist on VPS)
#   --no-acl    : do not restore GRANT/REVOKE commands
#   --dbname    : target database
#   --username  : connect as app_user (not postgres superuser)
#   --host      : explicit localhost (uses TCP, not Unix socket, for app_user)
#   --exit-on-error is intentionally NOT used — we want to capture non-fatal
#                   errors and inspect them rather than aborting on the first one.

RESTORE_EXIT_CODE=0
pg_restore \
    --no-owner \
    --no-acl \
    --dbname="${DB_NAME}" \
    --username="${DB_USER}" \
    --host="${DB_HOST}" \
    "${DUMP_FILE}" \
    2>"${LOG_FILE}" || RESTORE_EXIT_CODE=$?

# =============================================================================
# Step 4: Inspect pg_restore exit code and error log
# =============================================================================
info "Step 4: Inspecting pg_restore result (exit code: ${RESTORE_EXIT_CODE})..."

if [[ ${RESTORE_EXIT_CODE} -eq 0 ]]; then
    info "  ✓ pg_restore completed with no errors."
else
    warn "  pg_restore exited with code ${RESTORE_EXIT_CODE}."
    warn "  Inspecting error log for fatal vs. non-fatal errors..."

    # Count total error lines
    TOTAL_ERRORS=$(grep -c "^pg_restore: error:" "${LOG_FILE}" 2>/dev/null || echo "0")
    TOTAL_WARNINGS=$(grep -c "^pg_restore: warning:" "${LOG_FILE}" 2>/dev/null || echo "0")

    # Patterns that are ACCEPTABLE (non-fatal) per Requirement 2.6:
    #   - Missing Neon-internal roles (neon_superuser, neondb_owner, etc.)
    #   - Duplicate objects from idempotent migrations
    # NOTE: "could not execute query" is intentionally excluded — it is too
    #       broad and could mask real restore failures.
    ACCEPTABLE_PATTERN='role "neon|role "neondb|duplicate key value|already exists'

    FATAL_ERRORS=$(grep "^pg_restore: error:" "${LOG_FILE}" 2>/dev/null \
        | grep -vE "${ACCEPTABLE_PATTERN}" || true)

    ACCEPTABLE_ERRORS=$(grep "^pg_restore: error:" "${LOG_FILE}" 2>/dev/null \
        | grep -E "${ACCEPTABLE_PATTERN}" || true)

    ACCEPTABLE_COUNT=$(echo "${ACCEPTABLE_ERRORS}" | grep -c . 2>/dev/null || echo "0")
    FATAL_COUNT=$(echo "${FATAL_ERRORS}" | grep -c . 2>/dev/null || echo "0")

    echo ""
    echo "  Error summary:"
    echo "    Total errors:       ${TOTAL_ERRORS}"
    echo "    Total warnings:     ${TOTAL_WARNINGS}"
    echo "    Acceptable errors:  ${ACCEPTABLE_COUNT} (non-fatal, see comments in script)"
    echo "    Fatal errors:       ${FATAL_COUNT}"
    echo ""

    if [[ ${ACCEPTABLE_COUNT} -gt 0 ]]; then
        warn "  Acceptable (non-fatal) errors found — these are expected:"
        echo "${ACCEPTABLE_ERRORS}" | head -20 | while IFS= read -r line; do
            warn "    $line"
        done
        echo ""
    fi

    if [[ ${FATAL_COUNT} -gt 0 ]]; then
        error "  FATAL errors found — these require investigation:"
        echo "${FATAL_ERRORS}" | head -20 | while IFS= read -r line; do
            error "    $line"
        done
        echo ""
        error "  Full error log: ${LOG_FILE}"
        die "pg_restore encountered fatal errors. Aborting."
    else
        info "  ✓ All errors are non-fatal (acceptable per Requirement 2.6)."
        info "  Full error log saved to: ${LOG_FILE}"
    fi
fi

# =============================================================================
# Step 5: Transfer table ownership to app_user
# =============================================================================
info "Step 5: Transferring all table ownership to '${DB_USER}'..."

# pg_restore with --no-owner does not set table owners.
# This PL/pgSQL block iterates all public tables and sets the owner to app_user.
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<SQL
DO \$\$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
    LOOP
        EXECUTE 'ALTER TABLE public.' || quote_ident(r.tablename)
                || ' OWNER TO ${DB_USER}';
    END LOOP;
END \$\$;
SQL

info "  ✓ All public tables now owned by '${DB_USER}'."

# Also transfer sequence ownership
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<SQL
DO \$\$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = 'public'
    LOOP
        EXECUTE 'ALTER SEQUENCE public.' || quote_ident(r.sequence_name)
                || ' OWNER TO ${DB_USER}';
    END LOOP;
END \$\$;
SQL

info "  ✓ All public sequences now owned by '${DB_USER}'."

# =============================================================================
# Step 6: Verify restore by checking row counts in pg_stat_user_tables
# =============================================================================
info "Step 6: Verifying restore — row counts per table..."

echo ""
echo "  Table row counts (from pg_stat_user_tables):"
echo "  ─────────────────────────────────────────────────────────"

# Run ANALYZE first so pg_stat_user_tables has fresh statistics
sudo -u postgres psql -d "${DB_NAME}" -c "ANALYZE;" >/dev/null 2>&1 || true

sudo -u postgres psql -d "${DB_NAME}" <<SQL
SELECT
    schemaname,
    tablename,
    n_live_tup AS estimated_rows
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;
SQL

echo ""
info "  ✓ Row count verification complete."
info "  Compare these counts against the Neon source to confirm data integrity."

# =============================================================================
# Step 7: Quick connectivity test as app_user
# =============================================================================
info "Step 7: Testing connectivity as '${DB_USER}'..."

TABLE_COUNT=$(PGPASSWORD="${APP_USER_PASSWORD:-}" psql \
    "postgresql://${DB_USER}@${DB_HOST}/${DB_NAME}" \
    -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" \
    2>/dev/null || echo "ERROR")

if [[ "$TABLE_COUNT" == "ERROR" ]]; then
    warn "  Could not connect as '${DB_USER}' — check pg_hba.conf and the app_user password."
    warn "  The restore data is intact; this is a connectivity configuration issue."
else
    info "  ✓ Connected as '${DB_USER}'. Public tables visible: ${TABLE_COUNT}"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================================"
echo "  Task 2.2 (Part B) complete — Neon restore done"
echo "============================================================"
echo "  Database:   ${DB_NAME}"
echo "  Owner:      ${DB_USER}"
if [[ ${RESTORE_EXIT_CODE} -ne 0 ]]; then
    echo "  Errors:     Non-fatal only (see ${LOG_FILE})"
fi
echo ""
echo "  NEXT STEP: Run task 2.3 — apply Alembic migrations:"
echo "    cd /home/deploy/app/backend"
echo "    FLASK_ENV=production flask db upgrade head"
echo ""
echo "  Then verify row counts match the Neon source."
echo "============================================================"
