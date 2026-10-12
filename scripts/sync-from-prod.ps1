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

# Pinned VPS host key — same key material as VPS_HOST_KEY in vps-config.md.
# The script connects to $VPS_HOST (the name), so the known_hosts entry must
# list that name. An IP-only line makes OpenSSH exit 255:
# "No ED25519 host key is known for bbanalyzer.duckdns.org".
# SSH will fail if the server presents a different key (prevents MITM).
$VPS_KNOWN_HOSTS_FILE = "$HOME\AppData\Local\BBAnalyzer\vps_known_hosts"
$VPS_HOST_KEY  = "bbanalyzer.duckdns.org,5.161.200.46 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG3qSNJa8RTI+PBjSz6Z332g9LVw82et/xpdNnZ4KpcJ"

$LOG_DIR       = "$HOME\AppData\Local\BBAnalyzer\logs"
$DUMP_DIR      = "$HOME\AppData\Local\BBAnalyzer\dumps"
$LOG_FILE      = "$LOG_DIR\sync-from-prod.log"
$DUMP_FILE     = "$DUMP_DIR\prod_dump_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump"
$SCRIPT_PATH   = $MyInvocation.MyCommand.Path

# --- Install scheduled task --------------------------------------------------

function Install-SyncTask {
    # wscript.exe is a windowed program. Window style 0 keeps powershell
    # hidden for the whole run, including a failed sync. -WindowStyle Hidden
    # on powershell.exe is not enough: Task Scheduler still opens a console
    # when the task itself is the console process.
    $taskName = "BBAnalyzer - Sync from Prod"
    $dupName  = "BBAnalyzer - Sync Local DB from Production"
    $launcher = Join-Path (Split-Path $SCRIPT_PATH) "sync-from-prod-hidden.vbs"
    $launcherArgs = "//B //Nologo `"$launcher`""
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $actionOk = $existing -and ($existing.Actions[0].Execute -match 'wscript') -and ($existing.Actions[0].Arguments -eq $launcherArgs)
    if (-not ($existing -and $existing.Settings.Hidden -and $actionOk)) {
        $action   = New-ScheduledTaskAction `
            -Execute "wscript.exe" `
            -Argument $launcherArgs
        $triggers = @(
            (New-ScheduledTaskTrigger -Daily -At "02:00"),
            (New-ScheduledTaskTrigger -AtLogOn)
        )
        $settings = New-ScheduledTaskSettingsSet `
            -Hidden `
            -RunOnlyIfNetworkAvailable `
            -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1)
        Register-ScheduledTask `
            -TaskName $taskName `
            -Description "Syncs local PostgreSQL from production (bbanalyzer.duckdns.org)" `
            -Action $action `
            -Trigger $triggers `
            -Settings $settings `
            -RunLevel Highest `
            -Force | Out-Null
    }
    Unregister-ScheduledTask -TaskName $dupName -Confirm:$false -ErrorAction SilentlyContinue
}

function Hide-ConsoleIfScheduled {
    $parentId = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
    $parent = (Get-Process -Id $parentId -ErrorAction SilentlyContinue).ProcessName
    if ($parent -notin @("svchost", "taskeng", "wscript")) { return }
    if (-not ("BB.WinHide" -as [type])) {
        Add-Type -Namespace BB -Name WinHide -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("kernel32.dll")] public static extern System.IntPtr GetConsoleWindow();
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr hWnd, int nCmdShow);
"@
    }
    $hwnd = [BB.WinHide]::GetConsoleWindow()
    if ($hwnd -ne [IntPtr]::Zero) { [BB.WinHide]::ShowWindow($hwnd, 0) | Out-Null }
}

if ($Install) {
    Install-SyncTask
    Write-Host "Scheduled task installed (hidden)." -ForegroundColor Green
    Write-Host "  Runs: daily at 2:00 AM + at every Windows logon"
    Write-Host "  Trigger now: Start-ScheduledTask 'BBAnalyzer - Sync from Prod'"
    exit 0
}

# The saved task runs as highest, so a login run can rewrite itself even
# when this shell is not elevated. Hide the console before that work.
Hide-ConsoleIfScheduled
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) { Install-SyncTask }

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
    $empty = [System.IO.Path]::GetTempFileName()
    $tmp = "$empty.sql"
    # Windows PowerShell's UTF8 encoding writes a BOM. psql then fails the
    # statement ("syntax error at or near ï»¿DROP") and still exits 0, so the
    # old database is never dropped and pg_restore errors on top of it.
    [System.IO.File]::WriteAllText($tmp, $sql, [System.Text.UTF8Encoding]::new($false))
    [System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
    & $PSQL -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT -d $db -v ON_ERROR_STOP=1 -f $tmp
    $exitCode = $LASTEXITCODE
    Remove-Item $tmp, $empty -ErrorAction SilentlyContinue
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
    "-i", "`"$VPS_SSH_KEY`"",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "`"UserKnownHostsFile=$VPS_KNOWN_HOSTS_FILE`"",
    "-o", "BatchMode=yes",
    "${VPS_USER}@${VPS_HOST}",
    "pg_dump -U $VPS_DB_USER -h localhost -Fc $VPS_DB_NAME"
)

$sshErrFile = Join-Path $DUMP_DIR "ssh_stderr.txt"
$proc = Start-Process -FilePath "ssh" -ArgumentList $sshArgs `
    -RedirectStandardOutput $DUMP_FILE `
    -RedirectStandardError $sshErrFile `
    -Wait -PassThru -NoNewWindow

if ($proc.ExitCode -ne 0) {
    $sshErr = ""
    if (Test-Path $sshErrFile) {
        $sshErr = (Get-Content -Path $sshErrFile -Raw -ErrorAction SilentlyContinue)
        if ($sshErr) { $sshErr = $sshErr.Trim() }
    }
    Die "SSH/pg_dump failed (exit $($proc.ExitCode)): $sshErr"
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
& $PSQL -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT -d postgres -v ON_ERROR_STOP=1 -f $terminateSqlFile | Out-Null
if ($LASTEXITCODE -ne 0) {
    [System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")
    Die "failed to disconnect local sessions (exit $LASTEXITCODE)"
}
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")

Log "Dropping $LOCAL_DB_NAME ..."
RunPsql "postgres" "DROP DATABASE IF EXISTS $LOCAL_DB_NAME;"

Log "Creating $LOCAL_DB_NAME ..."
RunPsql "postgres" "CREATE DATABASE $LOCAL_DB_NAME;"

# --- Step 3: restore ---------------------------------------------------------

Log "Restoring dump into $LOCAL_DB_NAME ..."

$restoreErr = Join-Path $DUMP_DIR "pg_restore_stderr.txt"
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
$restoreProc = Start-Process -FilePath $PG_RESTORE -ArgumentList @(
    "-U", $LOCAL_DB_USER,
    "-h", $LOCAL_DB_HOST,
    "-p", $LOCAL_DB_PORT,
    "-d", $LOCAL_DB_NAME,
    "--no-owner", "--no-acl",
    "-j", "4",
    "`"$DUMP_FILE`""
) -RedirectStandardError $restoreErr -Wait -PassThru -NoNewWindow
$restoreExit = $restoreProc.ExitCode
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")

if ($restoreExit -ne 0) {
    $restoreTail = ""
    if (Test-Path $restoreErr) {
        $restoreTail = ((Get-Content -Path $restoreErr -Tail 20 -ErrorAction SilentlyContinue) -join " ")
    }
    Die "pg_restore failed (exit $restoreExit). Local database may be incomplete. $restoreTail"
}
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $LOCAL_DB_PASS, "Process")
# -t can return extra blank lines. An unguarded [int] cast then kills the
# task with no ERROR line in the log.
$userCountRaw = & $PSQL -X -v ON_ERROR_STOP=1 -U $LOCAL_DB_USER -h $LOCAL_DB_HOST -p $LOCAL_DB_PORT `
    -d $LOCAL_DB_NAME -t -A -c "SELECT COUNT(*) FROM users;"
$userCountExit = $LASTEXITCODE
[System.Environment]::SetEnvironmentVariable("PGPASSWORD", $null, "Process")
if ($userCountExit -ne 0) {
    Die "user count query failed (exit $userCountExit)"
}
$userToken = ("$userCountRaw" -split '\s+' | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1)
if (-not $userToken) {
    Die "user count was not a number: $userCountRaw"
}
$userCount = [int]$userToken

if (-not $userCount -or [int]$userCount -eq 0) {
    Die "Users table empty after restore - something went wrong"
}
Log "Verified: $userCount users in restored database"

# --- Step 4: run pending migrations ------------------------------------------

Log "Running Flask db upgrade ..."
$backendDir = Join-Path (Split-Path $PSScriptRoot -Parent) "backend"
$migrateLog = Join-Path $LOG_DIR "flask-db-upgrade.log"
Push-Location $backendDir
$migrateProc = Start-Process -FilePath "python" -ArgumentList "-m", "flask", "db", "upgrade" `
    -RedirectStandardOutput $migrateLog `
    -RedirectStandardError "$migrateLog.err" `
    -Wait -PassThru -NoNewWindow
Pop-Location
if ($migrateProc.ExitCode -ne 0) {
    $migrateErr = ""
    if (Test-Path "$migrateLog.err") {
        $migrateErr = (Get-Content -Path "$migrateLog.err" -Raw -ErrorAction SilentlyContinue)
        if ($migrateErr) { $migrateErr = $migrateErr.Trim() }
    }
    # A prod dump can be stamped with a revision this checkout does not
    # contain. The copy itself is already done; do not throw that restore away.
    if ($migrateErr -match "Unrecognized starting revision") {
        Log "WARNING: flask db upgrade skipped. This checkout does not know the production revision. Local data matches production."
    } else {
        Die "flask db upgrade failed (exit $($migrateProc.ExitCode)): $migrateErr"
    }
}

# --- Step 5: clean up old dumps (keep last 5) --------------------------------

Get-ChildItem -Path $DUMP_DIR -Filter "prod_dump_*.dump" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 5 |
    Remove-Item -Force

Log "=== Sync complete. Local DB matches production. ==="
