# ensure-local-prod-data.ps1
# Ensures the local PostgreSQL database has production lead data.
# Called automatically by python dev.py — no manual steps required.
#
# Strategy (when leads < 1,000):
#   1. Restore from cached dump (%LOCALAPPDATA%\BBAnalyzer\dumps\prod_dump.dump)
#   2. Download latest GitHub Actions prod-dump artifact (or trigger workflow)
#   3. Fall back to direct SSH sync if deploy key is configured
#
# Install daily background sync (optional):
#   .\scripts\ensure-local-prod-data.ps1 -Install

param([switch]$Install)

$ErrorActionPreference = "Stop"

$ProjectRoot  = Split-Path $PSScriptRoot -Parent
$MIN_LEADS    = 1000
$MIN_DUMP_BYTES = 10240
$DUMP_DIR     = "$env:LOCALAPPDATA\BBAnalyzer\dumps"
$CACHED_DUMP  = "$DUMP_DIR\prod_dump.dump"
$LOG_DIR      = "$env:LOCALAPPDATA\BBAnalyzer\logs"
$LOG_FILE     = "$LOG_DIR\ensure-local-prod-data.log"
$SCRIPT_PATH  = $MyInvocation.MyCommand.Path
$WORKFLOW     = "download-prod-dump.yml"
$DEFAULT_REPO = "bendstaples7/B-B-Commercial-RE-Underwriting"

$LOCAL_DB_USER = "postgres"
$LOCAL_DB_PASS = "postgres"
$LOCAL_DB_HOST = "localhost"
$LOCAL_DB_PORT = "5432"
$LOCAL_DB_NAME = "real_estate_analysis"
$PG_BIN        = "C:\Program Files\PostgreSQL\17\bin"
$PSQL          = "$PG_BIN\psql.exe"

$EnvFile = Join-Path $ProjectRoot ".env"
$VPS_SSH_KEY = "$HOME\.ssh\bbanalyzer_deploy"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -match '^VPS_SSH_KEY_PATH=(.*)$') {
            $VPS_SSH_KEY = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
}

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
    exit 1
}

function Get-LeadCount {
    if (-not (Test-Path $PSQL)) {
        Die "psql not found at $PSQL - install PostgreSQL 17"
    }
    [System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
    $raw = & $PSQL -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT `
        -d $LOCAL_DB_NAME -t -c "SELECT count(*) FROM leads;" 2>&1
    $exit = $LASTEXITCODE
    [System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")
    if ($exit -ne 0) {
        Die "Could not query leads table - is PostgreSQL running on localhost:5432?"
    }
    $text = ($raw | Out-String).Trim()
    return [int]$text
}

function Test-ValidDump([string]$Path) {
    return (Test-Path $Path) -and ((Get-Item $Path).Length -ge $MIN_DUMP_BYTES)
}

function Invoke-Restore([string]$DumpFile) {
    $restoreScript = Join-Path $PSScriptRoot "restore-prod-dump.ps1"
    if (-not (Test-Path $restoreScript)) {
        Die "restore-prod-dump.ps1 not found at $restoreScript"
    }
    Log "Restoring from $DumpFile ..."
    & powershell -NonInteractive -ExecutionPolicy Bypass -File $restoreScript -DumpFile $DumpFile
    if ($LASTEXITCODE -ne 0) {
        Die "restore-prod-dump.ps1 failed (exit $LASTEXITCODE)"
    }
}

function Resolve-GitHubRepo {
    try {
        $url = (git -C $ProjectRoot remote get-url origin 2>$null | Out-String).Trim()
        if ($url -match 'github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$') {
            return $Matches[1]
        }
    } catch { }
    return $DEFAULT_REPO
}

function Test-GhReady {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { return $false }
    gh auth status 2>&1 | Out-Null
    return $LASTEXITCODE -eq 0
}

function Invoke-GhFetchDump([string]$Repo) {
    if (-not (Test-GhReady)) {
        Log "GitHub CLI not authenticated - run: gh auth login"
        return $false
    }

    $cutoff = (Get-Date).ToUniversalTime().AddDays(-7)

    $runsJson = gh run list --workflow=$WORKFLOW -R $Repo --status=success `
        --limit=5 --json databaseId,createdAt 2>$null
    if ($runsJson) {
        $runs = $runsJson | ConvertFrom-Json
        foreach ($run in $runs) {
            $created = [DateTime]::Parse($run.createdAt).ToUniversalTime()
            if ($created -lt $cutoff) { continue }
            Log "Downloading prod dump from Actions run $($run.databaseId) ..."
            if (Test-Path $CACHED_DUMP) { Remove-Item $CACHED_DUMP -Force }
            gh run download $run.databaseId -R $Repo -n prod-dump -D $DUMP_DIR 2>&1 | Out-Null
            if (Test-ValidDump $CACHED_DUMP) { return $true }
        }
    }

    Log "No recent dump artifact - triggering $WORKFLOW on main ..."
    gh workflow run $WORKFLOW --ref main -R $Repo 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { return $false }

    Start-Sleep -Seconds 15
    $runId = $null
    for ($i = 0; $i -lt 90; $i++) {
        $runId = gh run list --workflow=$WORKFLOW -R $Repo --limit=1 `
            --json databaseId,status -q '.[0].databaseId' 2>$null
        $status = gh run list --workflow=$WORKFLOW -R $Repo --limit=1 `
            --json status -q '.[0].status' 2>$null
        if ($runId -and $status -eq "completed") { break }
        Start-Sleep -Seconds 10
    }
    if (-not $runId) { return $false }

    gh run watch $runId -R $Repo --exit-status 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { return $false }

    if (Test-Path $CACHED_DUMP) { Remove-Item $CACHED_DUMP -Force }
    gh run download $runId -R $Repo -n prod-dump -D $DUMP_DIR 2>&1 | Out-Null
    return (Test-ValidDump $CACHED_DUMP)
}

# --- Install scheduled task --------------------------------------------------

if ($Install) {
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$SCRIPT_PATH`""
    $triggers = @(
        (New-ScheduledTaskTrigger -Daily -At "03:00"),
        (New-ScheduledTaskTrigger -AtLogOn)
    )
    $settings = New-ScheduledTaskSettingsSet `
        -RunOnlyIfNetworkAvailable `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask `
        -TaskName "BBAnalyzer - Ensure Local Prod Data" `
        -Description "Keeps local PostgreSQL in sync with production (GitHub Actions dump)" `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Force | Out-Null
    Write-Host "Scheduled task installed: BBAnalyzer - Ensure Local Prod Data" -ForegroundColor Green
    Write-Host "  Runs: daily at 3:00 AM + at every Windows logon"
    exit 0
}

# --- Main --------------------------------------------------------------------

Log "=== ensure local prod data ==="

try {
    $leadCount = Get-LeadCount
} catch {
    Die $_.Exception.Message
}

if ($leadCount -ge $MIN_LEADS) {
    Log "Data ready: $leadCount leads"
    exit 0
}

Log "Only $leadCount leads (need $MIN_LEADS+) - auto-restoring ..."

if (Test-ValidDump $CACHED_DUMP) {
    $sizeMb = [math]::Round((Get-Item $CACHED_DUMP).Length / 1048576, 1)
    Log "Using cached dump ($sizeMb MB)"
    Invoke-Restore $CACHED_DUMP
    $leadCount = Get-LeadCount
    if ($leadCount -ge $MIN_LEADS) {
        Log "Restore complete: $leadCount leads"
        exit 0
    }
    Log "Cached dump restore left only $leadCount leads - fetching fresh dump"
}

$repo = Resolve-GitHubRepo
if (Invoke-GhFetchDump $repo) {
    Invoke-Restore $CACHED_DUMP
    $leadCount = Get-LeadCount
    if ($leadCount -ge $MIN_LEADS) {
        Log "Restore complete: $leadCount leads"
        exit 0
    }
}

if (Test-Path $VPS_SSH_KEY) {
    Log "Trying direct SSH sync (deploy key found) ..."
    $syncScript = Join-Path $PSScriptRoot "sync-from-prod.ps1"
    & powershell -NonInteractive -ExecutionPolicy Bypass -File $syncScript
    if ($LASTEXITCODE -eq 0) {
        $leadCount = Get-LeadCount
        Log "SSH sync complete: $leadCount leads"
        exit 0
    }
}

Die @"
Automatic production data restore failed.

Requirements for unattended restore:
  - PostgreSQL running on localhost:5432
  - GitHub CLI authenticated: gh auth login
  - Network access to GitHub Actions

Logs: $LOG_FILE
"@
