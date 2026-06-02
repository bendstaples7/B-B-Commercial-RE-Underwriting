# sync-from-prod.ps1
# Pulls a pg_dump from production and restores it to the local PostgreSQL DB.
# Safe to run unattended via Windows Task Scheduler.
#
# Usage (manual):      .\scripts\sync-from-prod.ps1
# Install task (once): .\scripts\sync-from-prod.ps1 -Install

param([switch]$Install)

$ErrorActionPreference = "Stop"

# --- Configuration -----------------------------------------------------------

$VPS_USER      = "deploy"
$VPS_HOST      = "bbanalyzer.duckdns.org"
$VPS_SSH_KEY   = "$HOME\.ssh\bbanalyzer_deploy"
$VPS_DB_USER   = "app_user"
$VPS_DB_NAME   = "real_estate_analysis"

$LOCAL_DB_USER = "postgres"
$LOCAL_DB_PASS = "postgres"
$LOCAL_DB_HOST = "localhost"
$LOCAL_DB_PORT = "5432"
$LOCAL_DB_NAME = "real_estate_analysis"

$PG_BIN        = "C:\Program Files\PostgreSQL\17\bin"
$PSQL          = "$PG_BIN\psql.exe"
$PG_RESTORE    = "$PG_BIN\pg_restore.exe"

# Pinned VPS host key — matches VPS_HOST_KEY in vps-config.md / GitHub secrets.
# SSH will fail if the server presents a different key (prevents MITM).
$VPS_KNOWN_HOSTS_FILE = "$HOME\AppData\Local\BBAnalyzer\vps_known_hosts"
$VPS_HOST_KEY  = "5.161.200.46 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG3qSNJa8RTI+PBjSz6Z332g9LVw82et/xpdNnZ4KpcJ"

$LOG_DIR       = "$HOME\AppData\Local\BBAnalyzer\logs"
$DUMP_DIR      = "$HOME\AppData\Local\BBAnalyzer\dumps"
$LOG_FILE      = "$LOG_DIR\sync-from-prod.log"
$DUMP_FILE     = "$DUMP_DIR\prod_dump_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump"
$SCRIPT_PATH   = $MyInvocation.MyCommand.Path

# --- Install scheduled task --------------------------------------------------

if ($Install) {
    $action   = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$SCRIPT_PATH`""
    $triggers = @(
        (New-ScheduledTaskTrigger -Daily -At "02:00"),
        (New-ScheduledTaskTrigger -AtLogOn)
    )
    $settings = New-ScheduledTaskSettingsSet `
        -RunOnlyIfNetworkAvailable `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask `
        -TaskName "BBAnalyzer - Sync from Prod" `
        -Description "Syncs local PostgreSQL from production (bbanalyzer.duckdns.org)" `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -RunLevel Highest `
        -Force | Out-Null
    Write-Host "Scheduled task installed." -ForegroundColor Green
    Write-Host "  Runs: daily at 2:00 AM + at every Windows logon"
    Write-Host "  Trigger now: Start-ScheduledTask 'BBAnalyzer - Sync from Prod'"
    exit 0
}

# --- Helpers -----------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $LOG_DIR  | Out-Null
New-Item -ItemType Directory -Force -Path $DUMP_DIR | Out-Null

function Log([string]$msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line
}

function Die([string]$msg) {
    Log "ERROR: $msg"
    [System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")
    exit 1
}

function RunPsql([string]$db, [string]$sql) {
    $tmp = [System.IO.Path]::GetTempFileName() + ".sql"
    Set-Content -Path $tmp -Value $sql -Encoding UTF8
    [System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
    & $PSQL -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT -d $db -f $tmp
    $exitCode = $LASTEXITCODE
    Remove-Item $tmp -ErrorAction SilentlyContinue
    [System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")
    if ($exitCode -ne 0) {
        Die "psql failed (exit $exitCode) running: $sql"
    }
}

# --- Pre-flight checks -------------------------------------------------------

if (-not (Test-Path $PSQL))       { Die "psql not found at $PSQL" }
if (-not (Test-Path $PG_RESTORE)) { Die "pg_restore not found at $PG_RESTORE" }
if (-not (Test-Path $VPS_SSH_KEY)){ Die "SSH key not found at $VPS_SSH_KEY" }

# Write the pinned VPS host key to a local known_hosts file so SSH can
# verify the server identity without disabling host-key checking.
# Use .NET WriteAllText with explicit no-BOM UTF-8 encoding — PowerShell's
# built-in UTF8 encoding adds a BOM which causes OpenSSH to reject the entry.
New-Item -ItemType Directory -Force -Path (Split-Path $VPS_KNOWN_HOSTS_FILE) | Out-Null
[System.IO.File]::WriteAllText(
    $VPS_KNOWN_HOSTS_FILE,
    "$VPS_HOST_KEY`n",
    [System.Text.UTF8Encoding]::new($false)
)

# --- Step 1: dump prod via SSH -----------------------------------------------

Log "=== prod to local sync starting ==="
Log "Dumping $VPS_DB_NAME from $VPS_HOST ..."

$sshArgs = @(
    "-i", $VPS_SSH_KEY,
    "-o", "StrictHostKeyChecking=yes",
    "-o", "UserKnownHostsFile=$VPS_KNOWN_HOSTS_FILE",
    "-o", "BatchMode=yes",
    "${VPS_USER}@${VPS_HOST}",
    "pg_dump -U $VPS_DB_USER -h localhost -Fc $VPS_DB_NAME"
)

$proc = Start-Process -FilePath "ssh" -ArgumentList $sshArgs `
    -RedirectStandardOutput $DUMP_FILE -Wait -PassThru -NoNewWindow

if ($proc.ExitCode -ne 0) {
    Die "SSH/pg_dump failed (exit $($proc.ExitCode))"
}

$dumpBytes = (Get-Item $DUMP_FILE).Length
Log "Dump received: $([math]::Round($dumpBytes / 1MB, 2)) MB"

if ($dumpBytes -lt 10240) {
    Die "Dump too small ($dumpBytes bytes) - aborting to protect local data"
}

# --- Step 2: drop and recreate local DB --------------------------------------

Log "Terminating connections to local $LOCAL_DB_NAME ..."
$terminateSqlFile = "$PSScriptRoot\terminate-connections.sql"
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
& $PSQL -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT -d postgres -f $terminateSqlFile | Out-Null
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")

Log "Dropping $LOCAL_DB_NAME ..."
RunPsql "postgres" "DROP DATABASE IF EXISTS $LOCAL_DB_NAME;"

Log "Creating $LOCAL_DB_NAME ..."
RunPsql "postgres" "CREATE DATABASE $LOCAL_DB_NAME;"

# --- Step 3: restore ---------------------------------------------------------

Log "Restoring dump into $LOCAL_DB_NAME ..."

[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
& $PG_RESTORE `
    -U $LOCAL_DB_USER `
    -h $LOCAL_DB_HOST `
    -p $LOCAL_DB_PORT `
    -d $LOCAL_DB_NAME `
    --no-owner --no-acl `
    -j 4 `
    $DUMP_FILE
$restoreExit = $LASTEXITCODE
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")

if ($restoreExit -ne 0) {
    Die "pg_restore failed (exit $restoreExit). Local database may be incomplete."
}
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
$userCount = (& $PSQL -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT `
    -d $LOCAL_DB_NAME -t -c "SELECT COUNT(*) FROM users;" 2>&1).Trim()
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")

if (-not $userCount -or [int]$userCount -eq 0) {
    Die "Users table empty after restore - something went wrong"
}
Log "Verified: $userCount users in restored database"

# --- Step 4: run pending migrations ------------------------------------------

Log "Running Flask db upgrade ..."
$backendDir = Join-Path (Split-Path $PSScriptRoot -Parent) "backend"
Push-Location $backendDir
$migrateProc = Start-Process -FilePath "python" -ArgumentList "-m", "flask", "db", "upgrade" `
    -Wait -PassThru -NoNewWindow
Pop-Location
if ($migrateProc.ExitCode -ne 0) {
    Die "flask db upgrade failed (exit $($migrateProc.ExitCode))"
}

# --- Step 5: clean up old dumps (keep last 5) --------------------------------

Get-ChildItem -Path $DUMP_DIR -Filter "prod_dump_*.dump" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 5 |
    Remove-Item -Force

Log "=== Sync complete. Local DB matches production. ==="
