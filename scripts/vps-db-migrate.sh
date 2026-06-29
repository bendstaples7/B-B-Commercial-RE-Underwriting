#!/usr/bin/env bash
# =============================================================================
# scripts/vps-db-migrate.sh  —  Standalone VPS Database Migration Script
#
# Designed to run ON THE VPS as the deploy user.  Performs a safe, verified
# Alembic schema migration on the VPS-local PostgreSQL database — independent
# of any code deployment pipeline.
#
# Usage:
#   bash /home/deploy/app/scripts/vps-db-migrate.sh              # upgrade to head
#   bash /home/deploy/app/scripts/vps-db-migrate.sh --check       # read-only check
#   bash /home/deploy/app/scripts/vps-db-migrate.sh --downgrade -1  # roll back 1 step
#
# What it does:
#   1. Pre-migration safety backup (pg_dump custom format)
#   2. Run `flask db upgrade head` (or downgrade N steps)
#   3. Verify the current revision matches the head
#   4. Verify table ownership remains correct
#   5. Report migration summary
#
# Requirements:
#   - Run as the 'deploy' user on the Hetzner VPS
#   - /home/deploy/app/backend/.env must exist with DATABASE_URL
#   - Python deps installed (pip install -r backend/requirements.txt)
#   - PostgreSQL running and accessible via DATABASE_URL
#
# Exit codes:
#   0 — migration applied or already at head
#   1 — pre-migration backup failed (no changes made)
#   2 — migration command failed (changes MAY have been partially applied)
#   3 — verification failed (migration ran but post-check did not pass)
#   4 — configuration error (missing files, wrong user)
# =============================================================================

set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────
APP_DIR="/home/deploy/app"
BACKEND_DIR="${APP_DIR}/backend"
ENV_FILE="${BACKEND_DIR}/.env"
BACKUP_DIR="/home/deploy/backups"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
MIGRATE_MODE="upgrade"
MIGRATE_TARGET="head"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { error "$*"; exit "${EXIT_CODE:-1}"; }

# ── Parse arguments ──────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --check)
            MIGRATE_MODE="check"
            ;;
        --downgrade)
            MIGRATE_MODE="downgrade"
            MIGRATE_TARGET=""  # must be the next arg
            ;;
        --help|-h)
            echo "Usage: $0 [--check|--downgrade N]"
            echo ""
            echo "  (no args)     Upgrade database schema to the current Alembic head."
            echo "  --check       Read-only check — report migration status, no changes."
            echo "  --downgrade N  Roll back N migration steps (e.g. --downgrade 1)."
            echo "  --help        Show this help message."
            exit 0
            ;;
        *)
            if [[ "$MIGRATE_MODE" == "downgrade" && -z "$MIGRATE_TARGET" ]]; then
                MIGRATE_TARGET="$arg"
            else
                die "Unknown argument: $arg. Usage: $0 [--check|--downgrade N]"
            fi
            ;;
    esac
done

# ── Guard: must be deploy user ────────────────────────────────────────────────
if [[ "$(whoami)" != "deploy" ]]; then
    EXIT_CODE=4
    die "This script must be run as the 'deploy' user. Current user: $(whoami)"
fi

# ── Guard: backend directory and .env must exist ──────────────────────────────
if [[ ! -d "$BACKEND_DIR" ]]; then
    EXIT_CODE=4
    die "Backend directory not found: $BACKEND_DIR"
fi
if [[ ! -f "$ENV_FILE" ]]; then
    EXIT_CODE=4
    die ".env file not found at $ENV_FILE. Create it first via scripts/vps-setup/07-create-env-file.sh"
fi

echo ""
echo "============================================================"
echo "  VPS Database Migration Script"
echo "  Mode:      ${MIGRATE_MODE}"
echo "  Started:   ${TIMESTAMP}"
echo "  Backend:   ${BACKEND_DIR}"
echo "============================================================"
echo ""

# ── Source .env for DATABASE_URL ──────────────────────────────────────────────
set -a
# shellcheck source=/home/deploy/app/backend/.env
source "$ENV_FILE"
set +a

export FLASK_ENV=production

# ── Verify flask is available ─────────────────────────────────────────────────
if ! command -v flask &>/dev/null; then
    if [[ -x "${HOME}/.local/bin/flask" ]]; then
        export PATH="${HOME}/.local/bin:${PATH}"
    else
        EXIT_CODE=4
        die "flask command not found. Run: pip install -r ${BACKEND_DIR}/requirements.txt"
    fi
fi

info "Flask version: $(flask --version 2>&1 | head -1 || echo 'unknown')"

# ── ── CHECK MODE ──────────────────────────────────────────────────────────────
if [[ "$MIGRATE_MODE" == "check" ]]; then
    info "Mode: read-only check — no changes will be made."
    echo ""

    # Check PostgreSQL connectivity
    info "Check 1: PostgreSQL connectivity..."
    if psql "${DATABASE_URL}" -tAc "SELECT 1;" &>/dev/null; then
        info "  ✓ PostgreSQL is reachable."
    else
        error "  ✗ PostgreSQL is NOT reachable via DATABASE_URL."
        exit 1
    fi

    # Check Alembic status
    info "Check 2: Alembic migration status..."
    cd "$BACKEND_DIR"
    CURRENT=$(flask db current 2>&1 || echo "ERROR")
    HEADS=$(flask db heads 2>&1 || echo "ERROR")
    echo ""
    echo "  Current revision:  ${CURRENT}"
    echo "  Head revision(s):  ${HEADS}"
    echo ""

    if echo "$CURRENT" | grep -q "(head)"; then
        info "  ✓ Database is at the current head revision."
    elif echo "$CURRENT" | grep -q "ERROR"; then
        warn "  Could not determine current revision."
    else
        warn "  Database is NOT at head — migration pending."
        UPGRADE_NEEDED=$(flask db upgrade --sql 2>/dev/null | wc -l || echo "unknown")
        info "  Pending SQL statements: ${UPGRADE_NEEDED}"
    fi

    # Check table ownership
    info "Check 3: Table ownership..."
    WRONG_OWNER=$(sudo -u postgres psql -tAc \
        "SELECT count(*) FROM pg_tables
         WHERE schemaname = 'public'
           AND tableowner <> 'app_user';" \
        -d "real_estate_analysis" 2>/dev/null || echo "ERROR")

    if [[ "$WRONG_OWNER" == "ERROR" ]]; then
        warn "  Could not verify table ownership."
    elif [[ "$WRONG_OWNER" -eq 0 ]]; then
        info "  ✓ All tables owned by 'app_user'."
    else
        warn "  ${WRONG_OWNER} table(s) not owned by 'app_user'."
    fi

    echo ""
    echo "============================================================"
    info "Check complete. Run without --check to apply any pending migrations."
    echo "============================================================"
    exit 0
fi

# ── ── UPGRADE / DOWNGRADE MODE ───────────────────────────────────────────────

# ── Step 1: Pre-migration safety backup ───────────────────────────────────────
info "Step 1: Pre-migration safety backup..."

mkdir -p "$BACKUP_DIR"

BACKUP_FILE="${BACKUP_DIR}/pre_migration_${TIMESTAMP}.dump"
info "  Backup target: ${BACKUP_FILE}"

if pg_dump -Fc "${DATABASE_URL}" -f "${BACKUP_FILE}"; then
    BACKUP_SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
    info "  ✓ Pre-migration backup created (${BACKUP_SIZE})."
else
    EXIT_CODE=1
    die "Pre-migration backup FAILED — aborting. No changes made."
fi

# ── Step 2: Run migration ─────────────────────────────────────────────────────
cd "$BACKEND_DIR"

if [[ "$MIGRATE_MODE" == "upgrade" ]]; then
    info "Step 2: Running 'flask db upgrade ${MIGRATE_TARGET}'..."
elif [[ "$MIGRATE_MODE" == "downgrade" ]]; then
    info "Step 2: Running 'flask db downgrade ${MIGRATE_TARGET}'..."
fi

MIGRATE_EXIT=0
MIGRATE_OUTPUT=$(flask db "${MIGRATE_MODE}" "${MIGRATE_TARGET}" 2>&1) || MIGRATE_EXIT=$?

if [[ ${MIGRATE_EXIT} -ne 0 ]]; then
    echo ""
    error "Migration command FAILED (exit code: ${MIGRATE_EXIT})."
    echo "  Output:"
    echo "${MIGRATE_OUTPUT}" | while IFS= read -r line; do echo "    ${line}"; done
    echo ""
    warn "  A pre-migration backup exists at: ${BACKUP_FILE}"
    warn "  To restore:  pg_restore -d \"\${DATABASE_URL}\" --clean \"${BACKUP_FILE}\""
    warn "  Then:        cd ${BACKEND_DIR} && flask db stamp <pre-migration-revision>"
    EXIT_CODE=2
    die "Migration failed. Database may be in a partially-migrated state."
fi

info "  ✓ Migration command completed successfully."

# ── Step 3: Verify post-migration state ───────────────────────────────────────
info "Step 3: Verifying post-migration state..."

CURRENT_REV=$(flask db current 2>&1 || echo "ERROR")

if [[ "$CURRENT_REV" != "ERROR" ]]; then
    info "  Current revision: ${CURRENT_REV}"

    if echo "$CURRENT_REV" | grep -q "(head)"; then
        info "  ✓ Database schema is at the current Alembic head."
    else
        warn "  Revision does not show '(head)' — this may be normal for a multi-head graph."
    fi
else
    warn "  Could not determine current revision (non-fatal)."
fi

# ── Step 4: Verify table ownership ────────────────────────────────────────────
info "Step 4: Verifying table ownership..."

WRONG_OWNER=$(sudo -u postgres psql -tAc \
    "SELECT count(*) FROM pg_tables
     WHERE schemaname = 'public'
       AND tableowner <> 'app_user';" \
    -d "real_estate_analysis" 2>/dev/null || echo "ERROR")

if [[ "$WRONG_OWNER" == "ERROR" ]]; then
    warn "  Could not verify table ownership (non-fatal)."
elif [[ "$WRONG_OWNER" -eq 0 ]]; then
    info "  ✓ All public tables owned by 'app_user'."
else
    warn "  ${WRONG_OWNER} table(s) not owned by 'app_user' — run scripts/vps-setup/08-alembic-migrate.sh to fix."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Migration complete"
echo "============================================================"
echo "  Mode:      ${MIGRATE_MODE} ${MIGRATE_TARGET}"
echo "  Backup:    ${BACKUP_FILE} (${BACKUP_SIZE:-unknown})"
echo "  Revision:  ${CURRENT_REV:-unknown}"
echo ""
echo "  To rollback:  bash $0 --downgrade 1"
echo "  To restore backup:"
echo "    pg_restore -d \"\${DATABASE_URL}\" --clean \"${BACKUP_FILE}\""
echo "    cd ${BACKEND_DIR} && flask db stamp <pre-migration-revision>"
echo "============================================================"
echo ""
info "Done."
