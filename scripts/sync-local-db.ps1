# sync-local-db.ps1
# Pulls a fresh pg_dump from the production VPS and restores it to the local
# PostgreSQL database. Overwrites ALL local data.
#
# Usage: .\scripts\sync-local-db.ps1
#
# Setup:
#   1. Copy scripts/sync-local-db.conf.example to scripts/sync-local-db.conf
#   2. Fill in your VPS and local DB credentials in sync-local-db.conf
#   3. Ensure your SSH key has access to the VPS (set SSH_KEY in conf or use default)
#   4. Ensure psql and pg_restore are available at the path set in $PG_BIN

$ErrorActionPreference = "Stop"

# ── Load config ───────────────────────────────────────────────────────────────
$configPath = "$PSScriptRoot\sync-local-db.conf"
if (-not (Test-Path $configPath)) {
    Write-Host "ERROR: Config file not found: $configPath" -ForegroundColor Red
    Write-Host "Copy scripts/sync-local-db.conf.example to scripts/sync-local-db.conf and fill in your values." -ForegroundColor Yellow
    exit 1
}

# Parse config file without Invoke-Expression (PSScriptAnalyzer-safe).
# Reads lines matching $VarName = "value" and assigns via Set-Variable.
Get-Content $configPath | Where-Object { $_ -match '^\$(\w+)\s*=\s*"([^"]*)"' -and $_ -notmatch '^\s*#' } | ForEach-Object {
    if ($_ -match '^\$(\w+)\s*=\s*"([^"]*)"') {
        Set-Variable -Name $Matches[1] -Value $Matches[2] -Scope Script
    }
}

# SSH key: use config-provided value if set, otherwise fall back to default
if ([string]::IsNullOrEmpty($SSH_KEY)) {
    $SSH_KEY = "$env:USERPROFILE\.ssh\bbanalyzer_deploy"
}
$KNOWN_HOSTS = "$env:USERPROFILE\.ssh\known_hosts"
$DUMP_FILE   = "$env:TEMP\prod_dump_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump"

# Validate config values are safe identifiers before interpolating into SQL
if ($null -ne $LOCAL_DB)   { $LOCAL_DB   = $LOCAL_DB.Trim() }
if ($null -ne $LOCAL_USER) { $LOCAL_USER = $LOCAL_USER.Trim() }
if ([string]::IsNullOrEmpty($LOCAL_DB))      { Write-Host "ERROR: LOCAL_DB is not set in sync-local-db.conf" -ForegroundColor Red; exit 1 }
if ([string]::IsNullOrEmpty($LOCAL_USER))    { Write-Host "ERROR: LOCAL_USER is not set in sync-local-db.conf" -ForegroundColor Red; exit 1 }
if ([string]::IsNullOrEmpty($VPS_DB_NAME))   { $VPS_DB_NAME = "real_estate_analysis" }
if ([string]::IsNullOrEmpty($VPS_DB_USER))   { $VPS_DB_USER = "app_user" }
if ([string]::IsNullOrEmpty($VPS_DB_PORT))   { $VPS_DB_PORT = "5432" }
if ($LOCAL_DB   -notmatch '^[a-zA-Z0-9_]+$') { Write-Host "ERROR: LOCAL_DB contains unsafe characters: [$LOCAL_DB]" -ForegroundColor Red; exit 1 }
if ($LOCAL_USER -notmatch '^[a-zA-Z0-9_]+$') { Write-Host "ERROR: LOCAL_USER contains unsafe characters: [$LOCAL_USER]" -ForegroundColor Red; exit 1 }

$sshBase = @(
    "-i", $SSH_KEY,
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "UserKnownHostsFile=$KNOWN_HOSTS",
    "$VPS_USER@$VPS_HOST"
)

# Track whether remote .pgpass_sync was written so finally can clean it up
$remotePassWritten = $false

# ── Main execution wrapped in try/finally so cleanup always runs ──────────────
try {
    # ── Step 1: Dump production DB ────────────────────────────────────────────
    Write-Host ""
    Write-Host "=== Syncing local DB from production ===" -ForegroundColor Cyan
    Write-Host "Step 1: Dumping production database from $VPS_HOST..." -ForegroundColor Yellow

    # Write VPS DB password to a remote .pgpass_sync using printf with positional
    # args to safely handle passwords/values containing single quotes or shell
    # metacharacters. Shell-escape: wrap in single quotes, replace ' with '\''.
    # pgpass-escape: escape backslashes first, then colons (pgpass field separator).
    $ShellEscape  = { param($s) "'" + $s.Replace("'", "'\\''") + "'" }
    $PgpassEscape = { param($s) $s.Replace('\', '\\').Replace(':', '\:') }

    $ePort = & $ShellEscape $VPS_DB_PORT
    $eName = & $ShellEscape $VPS_DB_NAME
    $eUser = & $ShellEscape $VPS_DB_USER
    $ePass = & $ShellEscape $VPS_DB_PASS
    $pgName = & $PgpassEscape $VPS_DB_NAME
    $pgUser = & $PgpassEscape $VPS_DB_USER
    $pgPass = & $PgpassEscape $VPS_DB_PASS

    $setupRemote = "printf '%s:%s:%s:%s:%s\n' '127.0.0.1' $ePort '$pgName' '$pgUser' '$pgPass' > ~/.pgpass_sync && chmod 600 ~/.pgpass_sync"

    & ssh @sshBase $setupRemote
    if ($LASTEXITCODE -ne 0) { throw "ERROR: Failed to write remote .pgpass_sync." }
    $remotePassWritten = $true

    # Dump using the remote .pgpass (no password in command line)
    $dumpCmd = "PGPASSFILE=~/.pgpass_sync pg_dump -h 127.0.0.1 -U $eUser -d $eName --no-owner --no-acl --format=custom"
    $sshProcess = Start-Process -FilePath "ssh" -ArgumentList (@($sshBase) + @($dumpCmd)) `
        -NoNewWindow -PassThru -RedirectStandardOutput $DUMP_FILE -Wait

    if ($sshProcess.ExitCode -ne 0) { throw "ERROR: pg_dump failed on VPS (exit code $($sshProcess.ExitCode))." }

    $dumpSize = (Get-Item $DUMP_FILE).Length / 1MB
    Write-Host "  Dump complete: $([math]::Round($dumpSize, 1)) MB" -ForegroundColor Green

    # Validate dump integrity before touching the local DB — prevents data loss
    # from a corrupted or partial dump overwriting good local data
    Write-Host "  Validating dump integrity..." -ForegroundColor Yellow
    & "$PG_BIN\pg_restore" -l $DUMP_FILE | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ERROR: Dump file validation failed - $DUMP_FILE appears corrupt or incomplete. Local DB was not modified." }

    # ── Step 2: Drop and recreate local DB ────────────────────────────────────
    Write-Host "Step 2: Recreating local database '$LOCAL_DB'..." -ForegroundColor Yellow

    $env:PGPASSWORD = $LOCAL_PASSWORD

    # Terminate existing connections — check exit code before DROP to give a clear error
    & "$PG_BIN\psql" -h localhost -U $LOCAL_USER -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LOCAL_DB' AND pid <> pg_backend_pid();" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: Failed to terminate existing connections (exit code $LASTEXITCODE). Proceeding anyway..." -ForegroundColor Yellow
    }

    & "$PG_BIN\psql" -h localhost -U $LOCAL_USER -d postgres -c "DROP DATABASE IF EXISTS `"$LOCAL_DB`";" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ERROR: Failed to drop local database." }

    & "$PG_BIN\psql" -h localhost -U $LOCAL_USER -d postgres -c "CREATE DATABASE `"$LOCAL_DB`" OWNER `"$LOCAL_USER`";" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ERROR: Failed to create local database." }

    Write-Host "  Local database recreated." -ForegroundColor Green

    # ── Step 3: Restore dump ──────────────────────────────────────────────────
    Write-Host "Step 3: Restoring dump to local database..." -ForegroundColor Yellow

    & "$PG_BIN\pg_restore" -h localhost -U $LOCAL_USER -d $LOCAL_DB --no-owner --no-acl --no-privileges --exit-on-error -j 4 $DUMP_FILE
    if ($LASTEXITCODE -ne 0) { throw "ERROR: pg_restore failed with exit code $LASTEXITCODE." }

    Write-Host "  Restore complete." -ForegroundColor Green

    # ── Step 4: Verify ────────────────────────────────────────────────────────
    Write-Host "Step 4: Verifying lead counts..." -ForegroundColor Yellow
    $result = & "$PG_BIN\psql" -h localhost -U $LOCAL_USER -d $LOCAL_DB -t -c "SELECT COALESCE(owner_user_id, 'NULL') as owner, COUNT(*) FROM leads GROUP BY owner_user_id ORDER BY COUNT(*) DESC;"
    if ($LASTEXITCODE -ne 0) { throw "ERROR: Verification query failed (exit code $LASTEXITCODE)." }
    Write-Host $result

    Write-Host ""
    Write-Host "=== Sync complete. Local DB matches production. ===" -ForegroundColor Cyan
}
finally {
    # Always clear credentials and remove dump artifact, even on early exit
    $env:PGPASSWORD = ""
    if ($DUMP_FILE -and (Test-Path $DUMP_FILE -ErrorAction SilentlyContinue)) {
        Remove-Item $DUMP_FILE -Force -ErrorAction SilentlyContinue
    }
    # Clean up remote .pgpass_sync if it was written
    if ($remotePassWritten) {
        & ssh @sshBase "rm -f ~/.pgpass_sync" 2>&1 | Out-Null
    }
}
