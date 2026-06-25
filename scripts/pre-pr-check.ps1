# Pre-PR readiness gate (Windows). See pre-pr-check.sh for the bash version.
param(
    [string]$Base = "origin/main",
    [switch]$NoServers,
    [switch]$NoTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Stop-PortListener {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" }
    foreach ($conn in $conns) {
        $procId = $conn.OwningProcess
        if ($procId) {
            Write-Host "Killing PID $procId on port $Port" -ForegroundColor Yellow
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-ForPort {
    param([int]$Port, [string]$Label)
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded {
            Write-Host "$Label listening on :$Port" -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Timed out waiting for $Label on :$Port"
}

Write-Host "=== Pre-PR check (base: $Base) ==="

Write-Host "`n--- Duplication / migration guards ---"
python (Join-Path $Root "scripts/check_duplication.py") --base $Base
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Stop-PortListener -Port 5000
Stop-PortListener -Port 3000

$backendJob = $null
$frontendJob = $null

try {
    if (-not $NoServers) {
        Write-Host "`n--- Starting dev servers ---"
        Set-Location $Root
        python dev.py check
        $backendJob = Start-Job -ScriptBlock {
            param($r)
            Set-Location $r
            python dev.py
        } -ArgumentList $Root
        Wait-ForPort -Port 5000 -Label "Backend"

        $frontendJob = Start-Job -ScriptBlock {
            param($r)
            Set-Location (Join-Path $r "frontend")
            npm run dev -- --host 127.0.0.1 --port 3000
        } -ArgumentList $Root
        Wait-ForPort -Port 3000 -Label "Frontend"
    }

    if (-not $NoTests) {
        Write-Host "`n--- Targeted tests (changed paths vs $Base) ---"
        $mapJson = python (Join-Path $Root "scripts/map_changed_to_tests.py") --base $Base --format json | ConvertFrom-Json

        Set-Location (Join-Path $Root "backend")
        $backendChanged = $mapJson.changed | Where-Object { $_ -like "backend/*" }
        if ($mapJson.backend.Count -gt 0 -and $mapJson.backend -ne @("tests/")) {
            Write-Host "pytest $($mapJson.backend -join ' ')" -ForegroundColor Yellow
            pytest -m "not performance" @($mapJson.backend)
        }
        elseif ($backendChanged) {
            Write-Host "No specific mapping — running full backend suite (excluding performance)" -ForegroundColor Yellow
            pytest -m "not performance"
        }
        else {
            Write-Host "No backend changes — skipping backend tests" -ForegroundColor Green
        }

        Set-Location (Join-Path $Root "frontend")
        $frontendChanged = $mapJson.changed | Where-Object { $_ -like "frontend/src/*" }
        if ($mapJson.frontend.Count -gt 0) {
            Write-Host "vitest $($mapJson.frontend -join ' ')" -ForegroundColor Yellow
            npm test -- --run @($mapJson.frontend)
        }
        elseif ($frontendChanged) {
            Write-Host "No co-located tests — running full frontend suite" -ForegroundColor Yellow
            npm test -- --run
        }
        else {
            Write-Host "No frontend src changes — skipping frontend tests" -ForegroundColor Green
        }
    }

    Write-Host "`n=== PR readiness checklist ==="
    Get-Content (Join-Path $Root "scripts/pre-pr-checklist.txt")
    Write-Host "Pre-PR check complete." -ForegroundColor Green
}
finally {
    if ($backendJob) { Stop-Job $backendJob -ErrorAction SilentlyContinue; Remove-Job $backendJob -Force -ErrorAction SilentlyContinue }
    if ($frontendJob) { Stop-Job $frontendJob -ErrorAction SilentlyContinue; Remove-Job $frontendJob -Force -ErrorAction SilentlyContinue }
    Stop-PortListener -Port 5000
    Stop-PortListener -Port 3000
}
