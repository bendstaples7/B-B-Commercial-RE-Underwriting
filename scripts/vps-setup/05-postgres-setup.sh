#!/usr/bin/env bash
# =============================================================================
# 05-postgres-setup.sh
# VPS Setup — Task 2.1: Create app_user PostgreSQL role and
#             real_estate_analysis database with schema privileges.
#
# Requirements: 2.1, 2.2
#
# Run as root on the Hetzner CX22 VPS (Ubuntu 22.04 LTS):
#   sudo bash 05-postgres-setup.sh
#
# The script reads the app_user password from the APP_USER_PASSWORD environment
# variable.  If the variable is not set it will prompt interactively.
#
# This script is IDEMPOTENT — safe to run multiple times.
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { error "$*"; exit 1; }

# ── Require root ─────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "This script must be run as root (use: sudo bash $0)"
fi

# ── Resolve app_user password ─────────────────────────────────────────────────
if [[ -z "${APP_USER_PASSWORD:-}" ]]; then
    echo ""
    warn "APP_USER_PASSWORD environment variable is not set."
    echo -n "  Enter a strong password for the app_user PostgreSQL role: "
    read -rs APP_USER_PASSWORD
    echo ""
    if [[ -z "$APP_USER_PASSWORD" ]]; then
        die "Password cannot be empty. Aborting."
    fi
fi

DB_NAME="real_estate_analysis"
PG_ROLE="app_user"

# ── Verify PostgreSQL 15 is running ───────────────────────────────────────────
info "Checking PostgreSQL service status..."
if ! systemctl is-active --quiet postgresql; then
    info "PostgreSQL is not running — attempting to start it..."
    systemctl start postgresql
    sleep 2
fi

if ! systemctl is-active --quiet postgresql; then
    die "PostgreSQL service failed to start. Check: journalctl -u postgresql"
fi
info "PostgreSQL service is active."

# =============================================================================
# Step 1: Create the app_user role (idempotent)
# =============================================================================
info "Step 1: Creating PostgreSQL role '$PG_ROLE'..."

# Use DO $$ ... $$ to handle the duplicate_object case gracefully
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_catalog.pg_roles WHERE rolname = '${PG_ROLE}'
    ) THEN
        CREATE ROLE ${PG_ROLE} WITH LOGIN PASSWORD '${APP_USER_PASSWORD}';
        RAISE NOTICE 'Role ${PG_ROLE} created.';
    ELSE
        -- Role exists: update the password to ensure it matches the supplied value
        ALTER ROLE ${PG_ROLE} WITH LOGIN PASSWORD '${APP_USER_PASSWORD}';
        RAISE NOTICE 'Role ${PG_ROLE} already exists — password updated.';
    END IF;
END
\$\$;
SQL

info "  Role '$PG_ROLE' is present."

# =============================================================================
# Step 2: Grant CREATEDB to app_user (needed by Alembic for test schemas)
# =============================================================================
info "Step 2: Granting CREATEDB privilege to '$PG_ROLE'..."
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "GRANT CREATEDB TO ${PG_ROLE};"
info "  CREATEDB granted."

# =============================================================================
# Step 3: Create the database (idempotent)
# =============================================================================
info "Step 3: Creating database '$DB_NAME' owned by '$PG_ROLE'..."

DB_EXISTS=$(sudo -u postgres psql -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}';" 2>/dev/null || true)

if [[ "$DB_EXISTS" == "1" ]]; then
    info "  Database '$DB_NAME' already exists — skipping creation."
else
    sudo -u postgres psql -v ON_ERROR_STOP=1 \
        -c "CREATE DATABASE ${DB_NAME} OWNER ${PG_ROLE};"
    info "  Database '$DB_NAME' created."
fi

# =============================================================================
# Step 4: Grant schema privileges and set default privileges
# =============================================================================
info "Step 4: Granting schema and default privileges on '$DB_NAME'..."

sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" <<SQL
-- Full access to the public schema
GRANT ALL PRIVILEGES ON SCHEMA public TO ${PG_ROLE};

-- Default privileges for tables created in the future
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${PG_ROLE};

-- Default privileges for sequences created in the future
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ${PG_ROLE};
SQL

info "  Schema and default privileges granted."

# =============================================================================
# Step 5: Verify app_user has NO superuser flag
# =============================================================================
info "Step 5: Verifying '$PG_ROLE' has no superuser privileges..."

SUPERUSER_FLAG=$(sudo -u postgres psql -tAc \
    "SELECT rolsuper FROM pg_roles WHERE rolname = '${PG_ROLE}';" 2>/dev/null || true)

if [[ "$SUPERUSER_FLAG" == "f" ]]; then
    info "  ✓ '$PG_ROLE' is NOT a superuser (rolsuper = f). Requirement 2.2 satisfied."
elif [[ "$SUPERUSER_FLAG" == "t" ]]; then
    die "  '$PG_ROLE' has superuser privileges! This violates Requirement 2.2. Aborting."
else
    die "  Could not determine superuser status for '$PG_ROLE'. Output: '$SUPERUSER_FLAG'"
fi

# =============================================================================
# Step 6: Verify role attributes (LOGIN, CREATEDB, no SUPERUSER)
# =============================================================================
info "Step 6: Full role attribute check (\du output for '$PG_ROLE')..."

sudo -u postgres psql -c "\du ${PG_ROLE}"

# Programmatic check for LOGIN and CREATEDB
ROLE_ATTRS=$(sudo -u postgres psql -tAc \
    "SELECT rolcanlogin, rolcreatedb FROM pg_roles WHERE rolname = '${PG_ROLE}';" \
    2>/dev/null || true)

ROLCANLOGIN=$(echo "$ROLE_ATTRS" | cut -d'|' -f1)
ROLCREATEDB=$(echo "$ROLE_ATTRS" | cut -d'|' -f2)

if [[ "$ROLCANLOGIN" != "t" ]]; then
    die "  '$PG_ROLE' does not have LOGIN privilege. Check role creation."
fi
info "  ✓ '$PG_ROLE' has LOGIN privilege."

if [[ "$ROLCREATEDB" != "t" ]]; then
    die "  '$PG_ROLE' does not have CREATEDB privilege. Check GRANT CREATEDB step."
fi
info "  ✓ '$PG_ROLE' has CREATEDB privilege."

# =============================================================================
# Step 7: Verify database ownership
# =============================================================================
info "Step 7: Verifying database '$DB_NAME' is owned by '$PG_ROLE'..."

DB_OWNER=$(sudo -u postgres psql -tAc \
    "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_database WHERE datname = '${DB_NAME}';" \
    2>/dev/null || true)

if [[ "$DB_OWNER" == "$PG_ROLE" ]]; then
    info "  ✓ Database '$DB_NAME' is owned by '$PG_ROLE'."
else
    die "  Database '$DB_NAME' owner is '$DB_OWNER', expected '$PG_ROLE'. Aborting."
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================================"
echo "  Task 2.1 complete — PostgreSQL role and database ready"
echo "============================================================"
echo "  Role:       $PG_ROLE"
echo "  Attributes: LOGIN, CREATEDB, no SUPERUSER"
echo "  Database:   $DB_NAME (owner: $PG_ROLE)"
echo ""
echo "  DATABASE_URL for backend/.env:"
echo "  postgresql://${PG_ROLE}:<password>@localhost:5432/${DB_NAME}"
echo ""
echo "  NEXT STEP: Run 06-clone-repo.sh (task 1.4) if not already done,"
echo "  then proceed to task 2.2 (data migration from Neon)."
echo "============================================================"
