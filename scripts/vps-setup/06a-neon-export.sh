#!/usr/bin/env bash
# =============================================================================
# 06a-neon-export.sh
# VPS Setup — Task 2.2 (Part A): Export data from Neon and copy to VPS.
#
# Requirements: 2.3
#
# Run LOCALLY (on the developer's machine) — NOT on the VPS.
#
# Usage:
#   bash 06a-neon-export.sh
#
# Required environment variables (set before running, or the script will prompt):
#   NEON_DATABASE_URL  — Full Neon connection string, e.g.:
#                        postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
#   VPS_IP             — Public IP address of the Hetzner VPS
#   VPS_USER           — SSH user on the VPS (default: deploy)
#
# Example (inline):
#   NEON_DATABASE_URL="postgresql://..." VPS_IP="1.2.3.4" bash 06a-neon-export.sh
#
# Prerequisites on the local machine:
#   - pg_dump (PostgreSQL client tools, version 15 recommended)
#   - ssh / scp with key-based access to the VPS as $VPS_USER
#
# This script is IDEMPOTENT — re-running it overwrites the previous dump file.
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

# ── Resolve required variables ────────────────────────────────────────────────
if [[ -z "${NEON_DATABASE_URL:-}" ]]; then
    echo ""
    warn "NEON_DATABASE_URL is not set."
    echo -n "  Enter the full Neon connection string: "
    read -r NEON_DATABASE_URL
    echo ""
    [[ -z "$NEON_DATABASE_URL" ]] && die "NEON_DATABASE_URL cannot be empty."
fi

if [[ -z "${VPS_IP:-}" ]]; then
    echo ""
    warn "VPS_IP is not set."
    echo -n "  Enter the VPS public IP address: "
    read -r VPS_IP
    echo ""
    [[ -z "$VPS_IP" ]] && die "VPS_IP cannot be empty."
fi

# Default SSH user to 'deploy' if not provided
VPS_USER="${VPS_USER:-deploy}"

# ── Verify pg_dump is available ───────────────────────────────────────────────
if ! command -v pg_dump &>/dev/null; then
    die "pg_dump not found. Install PostgreSQL client tools (version 15 recommended)."
fi

PG_DUMP_VERSION=$(pg_dump --version | head -1)
info "Using: $PG_DUMP_VERSION"

# ── Verify ssh/scp are available ─────────────────────────────────────────────
command -v ssh  &>/dev/null || die "ssh not found. Install OpenSSH client."
command -v scp  &>/dev/null || die "scp not found. Install OpenSSH client."

# ── Configuration ─────────────────────────────────────────────────────────────
DUMP_FILE="neon_export.dump"
DUMP_PATH="$(pwd)/${DUMP_FILE}"
VPS_DEST_PATH="/home/${VPS_USER}/${DUMP_FILE}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo ""
echo "============================================================"
echo "  Task 2.2 (Part A) — Neon Export"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Source:      Neon (connection string provided)"
echo "  Dump file:   $DUMP_PATH"
echo "  Destination: ${VPS_USER}@${VPS_IP}:${VPS_DEST_PATH}"
echo "============================================================"
echo ""

# =============================================================================
# Step 1: Export from Neon using pg_dump
# =============================================================================
info "Step 1: Exporting Neon database to '${DUMP_FILE}'..."
info "  Flags: --no-owner --no-acl --format=custom"
info "  (This may take a minute depending on database size...)"

# --no-owner  : omit ownership commands (Neon roles don't exist on the VPS)
# --no-acl    : omit GRANT/REVOKE commands (Neon ACLs don't apply on the VPS)
# --format=custom : compressed binary format; supports selective restore with pg_restore
pg_dump \
    --no-owner \
    --no-acl \
    --format=custom \
    --file="${DUMP_PATH}" \
    "${NEON_DATABASE_URL}"

if [[ ! -f "${DUMP_PATH}" ]]; then
    die "pg_dump completed but dump file not found at '${DUMP_PATH}'."
fi

DUMP_SIZE=$(du -sh "${DUMP_PATH}" | cut -f1)
info "  ✓ Dump created: ${DUMP_PATH} (${DUMP_SIZE})"

# =============================================================================
# Step 2: Verify the dump is readable (basic sanity check)
# =============================================================================
info "Step 2: Verifying dump integrity with pg_restore --list..."

# pg_restore --list reads the table of contents without actually restoring.
# A non-zero exit here means the dump file is corrupt or truncated.
OBJECT_COUNT=$(pg_restore --list "${DUMP_PATH}" 2>/dev/null | wc -l | tr -d ' ')
info "  ✓ Dump contains ${OBJECT_COUNT} objects in the table of contents."

if [[ "$OBJECT_COUNT" -eq 0 ]]; then
    warn "  Dump table of contents is empty — the source database may be empty."
    warn "  Proceeding anyway; pg_restore on the VPS will be a no-op."
fi

# =============================================================================
# Step 3: Copy dump to VPS via scp
# =============================================================================
info "Step 3: Copying dump to VPS (${VPS_USER}@${VPS_IP}:${VPS_DEST_PATH})..."
info "  (This may take a minute depending on file size and network speed...)"

scp "${DUMP_PATH}" "${VPS_USER}@${VPS_IP}:${VPS_DEST_PATH}"

info "  ✓ Dump copied to VPS at '${VPS_DEST_PATH}'."

# =============================================================================
# Step 4: Verify the file arrived on the VPS
# =============================================================================
info "Step 4: Verifying dump file on VPS..."

REMOTE_SIZE=$(ssh "${VPS_USER}@${VPS_IP}" "du -sh '${VPS_DEST_PATH}' | cut -f1" 2>/dev/null || echo "unknown")
info "  ✓ Remote file size: ${REMOTE_SIZE}"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================================"
echo "  Task 2.2 (Part A) complete — Neon export done"
echo "============================================================"
echo "  Local dump:   ${DUMP_PATH}"
echo "  Remote dump:  ${VPS_USER}@${VPS_IP}:${VPS_DEST_PATH}"
echo ""
echo "  NEXT STEP: SSH to the VPS and run:"
echo "    bash /home/${VPS_USER}/app/scripts/vps-setup/06b-neon-restore.sh"
echo ""
echo "  Or copy the restore script first:"
echo "    scp scripts/vps-setup/06b-neon-restore.sh \\"
echo "        ${VPS_USER}@${VPS_IP}:/home/${VPS_USER}/app/scripts/vps-setup/"
echo "    ssh ${VPS_USER}@${VPS_IP} 'bash /home/${VPS_USER}/app/scripts/vps-setup/06b-neon-restore.sh'"
echo "============================================================"
