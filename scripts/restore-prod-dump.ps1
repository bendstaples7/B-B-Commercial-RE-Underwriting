# restore-prod-dump.ps1
# Restore a production pg_dump (custom format) into local PostgreSQL.
#
# Usage:
#   # After downloading the "prod-dump" artifact from GitHub Actions:
#   .\scripts\restore-prod-dump.ps1 -DumpFile .\prod_dump.dump

param(
    [Parameter(Mandatory = $true)]
    [string]$DumpFile
)

$ErrorActionPreference = "Stop"

$LOCAL_DB_USER = "postgres"
$LOCAL_DB_PASS = "postgres"
$LOCAL_DB_HOST = "localhost"
$LOCAL_DB_PORT = "5432"
$LOCAL_DB_NAME = "real_estate_analysis"

$PG_BIN     = "C:\Program Files\PostgreSQL\17\bin"
$PSQL       = "$PG_BIN\psql.exe"
$PG_RESTORE = "$PG_BIN\pg_restore.exe"

function Die([string]$msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
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

if (-not (Test-Path $DumpFile)) {
    Die "Dump file not found: $DumpFile"
}

$dumpBytes = (Get-Item $DumpFile).Length
if ($dumpBytes -lt 10240) {
    Die "Dump too small ($dumpBytes bytes) - file may be corrupt"
}

if (-not (Test-Path $PSQL))       { Die "psql not found at $PSQL" }
if (-not (Test-Path $PG_RESTORE)) { Die "pg_restore not found at $PG_RESTORE" }

Write-Host "Restoring $([math]::Round($dumpBytes / 1MB, 2)) MB from $DumpFile ..."

$terminateSqlFile = Join-Path $PSScriptRoot "terminate-connections.sql"
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
& $PSQL -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT -d postgres -f $terminateSqlFile | Out-Null
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")

Write-Host "Dropping $LOCAL_DB_NAME ..."
RunPsql "postgres" "DROP DATABASE IF EXISTS $LOCAL_DB_NAME;"

Write-Host "Creating $LOCAL_DB_NAME ..."
RunPsql "postgres" "CREATE DATABASE $LOCAL_DB_NAME;"

Write-Host "Running pg_restore ..."
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
& $PG_RESTORE `
    -U $LOCAL_DB_USER `
    -h $LOCAL_DB_HOST `
    -p $LOCAL_DB_PORT `
    -d $LOCAL_DB_NAME `
    --no-owner --no-acl `
    -j 4 `
    $DumpFile
$restoreExit = $LASTEXITCODE
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")

if ($restoreExit -ne 0) {
    Die "pg_restore failed (exit $restoreExit). Local database may be incomplete."
}

[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
$userCount = (& $PSQL -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT `
    -d $LOCAL_DB_NAME -t -c "SELECT COUNT(*) FROM users;" 2>&1).Trim()
$leadCount = (& $PSQL -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT `
    -d $LOCAL_DB_NAME -t -c "SELECT COUNT(*) FROM leads;" 2>&1).Trim()
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")

Write-Host "Verified: $userCount users, $leadCount leads"

Write-Host "Running flask db upgrade ..."
$backendDir = Join-Path (Split-Path $PSScriptRoot -Parent) "backend"
Push-Location $backendDir
$migrateProc = Start-Process -FilePath "python" -ArgumentList "-m", "flask", "db", "upgrade" `
    -Wait -PassThru -NoNewWindow
Pop-Location
if ($migrateProc.ExitCode -ne 0) {
    Die "flask db upgrade failed (exit $($migrateProc.ExitCode))"
}

Write-Host "Restore complete." -ForegroundColor Green
