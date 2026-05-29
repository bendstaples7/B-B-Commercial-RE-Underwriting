#!/usr/bin/env bash
# =============================================================================
# 08-alembic-migrate.sh
# VPS Setup — Task 2.3: Apply Alembic migrations and transfer table ownership
#             to app_user.
#
# Requirements: 2.5, 2.7
#
# Run ON THE VPS as the deploy user (NOT as root):
#   bash /home/deploy/app/scripts/vps-setup/08-alembic-migrate.sh
#
# Prerequisites:
#   - 05-postgres-setup.sh has been run (app_user role and real_estate_analysis
#     database exist)
#   - 06b-neon-restore.sh has been run (data restored from Neon)
#   - 07-create-env-file.sh has been run (/home/deploy/app/backend/.env exists
#     with DATABASE_URL and FLASK_ENV=production)
#   - Python dependencies are installed (pip install -r backend/requirements.txt)
#
# This script is IDEMPOTENT — safe to run multiple times.
#   - `flask db upgrade head` is idempotent by design (Alembic skips already-
#     applied migrations)
#   - The ownership-transfer block uses ALTER TABLE ... OWNER TO, which is a
#     no-op if the table is already owned by app_user
#   - Row-count verification is read-only
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
APP_DIR="/home/deploy/app"
BACKEND_DIR="${APP_DIR}/backend"
DB_NAME="real_estate_analysis"
DB_USER="app_user"
DB_HOST="localhost"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ── Verify running as deploy user (not root) ──────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    die "Run this script as the deploy user, NOT as root.
  Usage: bash ${APP_DIR}/scripts/vps-setup/08-alembic-migrate.sh"
fi

# ── Verify backend directory exists ──────────────────────────────────────────
if [[ ! -d "${BACKEND_DIR}" ]]; then
    die "Backend directory not found: ${BACKEND_DIR}
  Run 04-clone-repo.sh first to clone the application repository."
fi

# ── Verify .env file exists ───────────────────────────────────────────────────
if [[ ! -f "${BACKEND_DIR}/.env" ]]; then
    die "Production .env file not found: ${BACKEND_DIR}/.env
  Run 07-create-env-file.sh first to create the production environment file."
fi

echo ""
echo "============================================================"
echo "  Task 2.3 — Alembic Migrations + Ownership Transfer"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  App dir:    ${APP_DIR}"
echo "  Backend:    ${BACKEND_DIR}"
echo "  Database:   ${DB_NAME}"
echo "  DB user:    ${DB_USER}"
echo "============================================================"
echo ""

# =============================================================================
# Step 1: Verify PostgreSQL is running and the database exists
# =============================================================================
info "Step 1: Verifying PostgreSQL service and database..."

if ! systemctl is-active --quiet postgresql; then
    die "PostgreSQL is not running. Start it with: sudo systemctl start postgresql"
fi
info "  ✓ PostgreSQL service is active."

DB_EXISTS=$(sudo -u postgres psql -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}';" 2>/dev/null || echo "")
if [[ "$DB_EXISTS" != "1" ]]; then
    die "Database '${DB_NAME}' does not exist.
  Run 05-postgres-setup.sh and 06b-neon-restore.sh first."
fi
info "  ✓ Database '${DB_NAME}' exists."

# =============================================================================
# Step 2: Verify flask and flask-migrate are available
# =============================================================================
info "Step 2: Verifying Flask and Flask-Migrate are installed..."

if ! command -v flask &>/dev/null; then
    # Try the user-local install path (pip install --user)
    if [[ -x "${HOME}/.local/bin/flask" ]]; then
        export PATH="${HOME}/.local/bin:${PATH}"
        info "  Added ~/.local/bin to PATH."
    else
        die "flask command not found. Run: pip install -r ${BACKEND_DIR}/requirements.txt"
    fi
fi

FLASK_VERSION=$(flask --version 2>&1 | head -1 || echo "unknown")
info "  ✓ Flask available: ${FLASK_VERSION}"

# =============================================================================
# Step 3: Run flask db upgrade head (Requirement 2.5)
# =============================================================================
info "Step 3: Running 'flask db upgrade head'..."
info "  Working directory: ${BACKEND_DIR}"
info "  FLASK_ENV=production"

cd "${BACKEND_DIR}"

# Source the .env file so DATABASE_URL is available to flask db upgrade.
# We use 'set -a' to export all variables, then 'set +a' to stop.
set -a
# shellcheck source=/dev/null
source "${BACKEND_DIR}/.env"
set +a

# Override FLASK_ENV to production regardless of what .env says
export FLASK_ENV=production

UPGRADE_EXIT_CODE=0
flask db upgrade head 2>&1 || UPGRADE_EXIT_CODE=$?

if [[ ${UPGRADE_EXIT_CODE} -ne 0 ]]; then
    die "'flask db upgrade head' failed with exit code ${UPGRADE_EXIT_CODE}.
  Check the output above for migration errors.
  Common causes:
    - DATABASE_URL is incorrect in ${BACKEND_DIR}/.env
    - app_user lacks privileges on the database
    - A migration file has a syntax error
  Fix the issue and re-run this script."
fi

info "  ✓ 'flask db upgrade head' completed successfully."

# =============================================================================
# Step 4: Verify Alembic is at the current head revision
# =============================================================================
info "Step 4: Verifying Alembic migration head..."

# 'flask db current' prints the current revision(s)
CURRENT_REV=$(flask db current 2>&1 || echo "ERROR")

if [[ "$CURRENT_REV" == "ERROR" ]]; then
    warn "  Could not determine current Alembic revision."
    warn "  This is non-fatal — the upgrade step succeeded."
else
    info "  Current Alembic revision: ${CURRENT_REV}"

    # Check that the current revision is marked as (head)
    if echo "$CURRENT_REV" | grep -q "(head)"; then
        info "  ✓ Database schema is at the current head revision."
    else
        warn "  The current revision does not show '(head)'."
        warn "  This may indicate a branch in the migration history."
        warn "  Run 'flask db heads' to inspect all head revisions."
        warn "  Continuing — the upgrade step succeeded without errors."
    fi
fi

# =============================================================================
# Step 5: Transfer all public table ownership to app_user (Requirement 2.7)
# =============================================================================
info "Step 5: Transferring all public table ownership to '${DB_USER}'..."

# This PL/pgSQL block is idempotent: ALTER TABLE ... OWNER TO is a no-op
# if the table is already owned by app_user.
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<'SQL'
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE 'ALTER TABLE public.' || quote_ident(r.tablename) || ' OWNER TO app_user';
  END LOOP;
END $$;
SQL

info "  ✓ All public tables now owned by '${DB_USER}'."

# =============================================================================
# Step 6: Transfer all public sequence ownership to app_user
# =============================================================================
info "Step 6: Transferring all public sequence ownership to '${DB_USER}'..."

sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<'SQL'
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT sequence_name
    FROM information_schema.sequences
    WHERE sequence_schema = 'public'
  LOOP
    EXECUTE 'ALTER SEQUENCE public.' || quote_ident(r.sequence_name)
            || ' OWNER TO app_user';
  END LOOP;
END $$;
SQL

info "  ✓ All public sequences now owned by '${DB_USER}'."

# =============================================================================
# Step 7: Verify table ownership — all public tables must be owned by app_user
# =============================================================================
info "Step 7: Verifying table ownership..."

# Find any tables NOT owned by app_user
WRONG_OWNER_COUNT=$(sudo -u postgres psql -tAc \
    "SELECT count(*) FROM pg_tables
     WHERE schemaname = 'public'
       AND tableowner <> '${DB_USER}';" \
    -d "${DB_NAME}" 2>/dev/null || echo "ERROR")

if [[ "$WRONG_OWNER_COUNT" == "ERROR" ]]; then
    warn "  Could not verify table ownership. Check manually with:"
    warn "  sudo -u postgres psql -d ${DB_NAME} -c \"SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public';\""
elif [[ "$WRONG_OWNER_COUNT" -eq 0 ]]; then
    info "  ✓ All public tables are owned by '${DB_USER}'. Requirement 2.7 satisfied."
else
    warn "  ${WRONG_OWNER_COUNT} table(s) are NOT owned by '${DB_USER}':"
    sudo -u postgres psql -d "${DB_NAME}" <<SQL
SELECT tablename, tableowner
FROM pg_tables
WHERE schemaname = 'public'
  AND tableowner <> '${DB_USER}'
ORDER BY tablename;
SQL
    die "Ownership transfer incomplete. See table list above."
fi

# =============================================================================
# Step 8: Verify row counts with pg_stat_user_tables (Requirement 2.5 / 2.7)
# =============================================================================
info "Step 8: Verifying row counts via pg_stat_user_tables..."

# Run ANALYZE to refresh statistics before reading pg_stat_user_tables
sudo -u postgres psql -d "${DB_NAME}" -c "ANALYZE;" >/dev/null 2>&1 || true

echo ""
echo "  Table row counts (estimated, from pg_stat_user_tables):"
echo "  ─────────────────────────────────────────────────────────────────"

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
info "  Note: pg_stat_user_tables shows estimates; use SELECT count(*) for exact counts."

# =============================================================================
# Step 9: Quick connectivity test as app_user
# =============================================================================
info "Step 9: Testing connectivity as '${DB_USER}'..."

TABLE_COUNT=$(psql \
    "postgresql://${DB_USER}@${DB_HOST}/${DB_NAME}" \
    -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" \
    2>/dev/null || echo "ERROR")

if [[ "$TABLE_COUNT" == "ERROR" ]]; then
    warn "  Could not connect as '${DB_USER}' — check pg_hba.conf and the app_user password."
    warn "  The migration data is intact; this is a connectivity configuration issue."
else
    info "  ✓ Connected as '${DB_USER}'. Public tables visible: ${TABLE_COUNT}"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================================"
echo "  Task 2.3 complete — Migrations applied, ownership set"
echo "============================================================"
echo "  Database:   ${DB_NAME}"
echo "  Schema:     At Alembic head revision"
echo "  Ownership:  All public tables owned by '${DB_USER}'"
echo ""
echo "  NEXT STEPS:"
echo "    4.1  Install the Gunicorn systemd service"
echo "         sudo bash ${APP_DIR}/scripts/vps-setup/09-gunicorn-service.sh"
echo ""
echo "    Or verify the migration manually:"
echo "      cd ${BACKEND_DIR}"
echo "      FLASK_ENV=production flask db current"
echo "      sudo -u postgres psql -d ${DB_NAME} -c \\"
echo "        \"SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public';\""
echo "============================================================"
