# sync-local-db.ps1
# Pulls a fresh pg_dump from the production VPS and restores it to the local
# PostgreSQL database. Overwrites ALL local data.
#
# Usage: .\scripts\sync-local-db.ps1
#
# Setup:
#   1. Copy scripts/sync-local-db.conf.example to scripts/sync-local-db.conf
#   2. Fill in your VPS and local DB credentials in sync-local-db.conf
#   3. Ensure ~/.ssh/bbanalyzer_deploy has SSH access to the VPS
#   4. Ensure psql and pg_restore are available at the path set in $PG_BIN

$ErrorActionPreference = "Stop"

# ── Load config ───────────────────────────────────────────────────────────────
$configPath = "$PSScriptRoot\sync-local-db.conf"
if (-not (Test-Path $configPath)) {
    Write-Host "ERROR: Config file not found: $configPath" -ForegroundColor Red
    Write-Host "Copy scripts/sync-local-db.conf.example to scripts/sync-local-db.conf and fill in your values." -ForegroundColor Yellow
    exit 1
}
. $configPath

$SSH_KEY  = "$env:USERPROFILE\.ssh\bbanalyzer_deploy"
$DUMP_FILE = "$env:TEMP\prod_dump_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump"

# ── Step 1: Dump production DB ─────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Syncing local DB from production ===" -ForegroundColor Cyan
Write-Host "Step 1: Dumping production database from $VPS_HOST..." -ForegroundColor Yellow

$sshArgs = @(
    "-i", $SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "$VPS_USER@$VPS_HOST",
    "PGPASSWORD='$VPS_DB_PASS' pg_dump -h 127.0.0.1 -U app_user -d real_estate_analysis --no-owner --no-acl --format=custom"
)

$sshProcess = Start-Process -FilePath "ssh" -ArgumentList $sshArgs -NoNewWindow -PassThru -RedirectStandardOutput $DUMP_FILE -Wait
if ($sshProcess.ExitCode -ne 0) {
    Write-Host "ERROR: pg_dump failed on VPS (exit code $($sshProcess.ExitCode))." -ForegroundColor Red
    exit 1
}

$dumpSize = (Get-Item $DUMP_FILE).Length / 1MB
Write-Host "  Dump complete: $([math]::Round($dumpSize, 1)) MB" -ForegroundColor Green

# ── Step 2: Drop and recreate local DB ────────────────────────────────────────
Write-Host "Step 2: Recreating local database '$LOCAL_DB'..." -ForegroundColor Yellow

$env:PGPASSWORD = $LOCAL_PASSWORD

# Terminate existing connections so DROP DATABASE doesn't fail
& "$PG_BIN\psql" -U $LOCAL_USER -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LOCAL_DB' AND pid <> pg_backend_pid();" | Out-Null
& "$PG_BIN\psql" -U $LOCAL_USER -d postgres -c "DROP DATABASE IF EXISTS $LOCAL_DB;" | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to drop local database." -ForegroundColor Red; exit 1 }

& "$PG_BIN\psql" -U $LOCAL_USER -d postgres -c "CREATE DATABASE $LOCAL_DB OWNER $LOCAL_USER;" | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to create local database." -ForegroundColor Red; exit 1 }

Write-Host "  Local database recreated." -ForegroundColor Green

# ── Step 3: Restore dump ───────────────────────────────────────────────────────
Write-Host "Step 3: Restoring dump to local database..." -ForegroundColor Yellow

& "$PG_BIN\pg_restore" -U $LOCAL_USER -d $LOCAL_DB --no-owner --no-acl --no-privileges -j 4 $DUMP_FILE
# pg_restore exits 1 for non-fatal warnings — only fail on exit code > 1
if ($LASTEXITCODE -gt 1) {
    Write-Host "ERROR: pg_restore failed with exit code $LASTEXITCODE." -ForegroundColor Red
    exit 1
}

Write-Host "  Restore complete." -ForegroundColor Green

# ── Step 4: Verify ─────────────────────────────────────────────────────────────
Write-Host "Step 4: Verifying lead counts..." -ForegroundColor Yellow
$result = & "$PG_BIN\psql" -U $LOCAL_USER -d $LOCAL_DB -t -c "SELECT COALESCE(owner_user_id, 'NULL') as owner, COUNT(*) FROM leads GROUP BY owner_user_id ORDER BY COUNT(*) DESC;"
Write-Host $result

# ── Cleanup ────────────────────────────────────────────────────────────────────
Remove-Item $DUMP_FILE -Force
$env:PGPASSWORD = ""

Write-Host ""
Write-Host "=== Sync complete. Local DB matches production. ===" -ForegroundColor Cyan
