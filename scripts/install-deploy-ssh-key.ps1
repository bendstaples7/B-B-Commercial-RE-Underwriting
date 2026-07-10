# install-deploy-ssh-key.ps1
# Install the VPS deploy private key to ~/.ssh/bbanalyzer_deploy and validate
# it matches the authorized key on the VPS.
#
# Usage:
#   .\scripts\install-deploy-ssh-key.ps1 -KeyFile C:\path\to\bbanalyzer_deploy
#   .\scripts\install-deploy-ssh-key.ps1   # uses VPS_SSH_KEY_PATH from .env
#   .\scripts\install-deploy-ssh-key.ps1 -ValidateOnly

param(
    [string]$KeyFile,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$EnvFile = Join-Path $ProjectRoot ".env"
$TargetKey = "$env:USERPROFILE\.ssh\bbanalyzer_deploy"
$ExpectedPubFragment = "AAAAC3NzaC1lZDI1NTE5AAAAIHJY8BtrSPEkCU2aoDnAz46f2RXovrbkhsn86e5mh7zP"

if (-not $KeyFile -and (Test-Path $EnvFile)) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -match '^VPS_SSH_KEY_PATH=(.*)$') {
            $KeyFile = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
}

if (-not $ValidateOnly) {
    if (-not $KeyFile -or -not (Test-Path $KeyFile)) {
        Write-Host "ERROR: Deploy private key not found." -ForegroundColor Red
        Write-Host "  Set VPS_SSH_KEY_PATH in .env to the key file from Hetzner setup,"
        Write-Host "  or pass -KeyFile explicitly."
        exit 1
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $TargetKey) | Out-Null

    $pubPreview = & ssh-keygen -y -f $KeyFile 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Could not read public key from $KeyFile" -ForegroundColor Red
        Write-Host $pubPreview
        exit 1
    }
    if ($pubPreview -notmatch [regex]::Escape($ExpectedPubFragment)) {
        Write-Host "ERROR: Key file does not match the deploy key authorized on the VPS."
        Write-Host "Use the private key from Hetzner setup — do not run ssh-keygen for a new pair."
        exit 1
    }

    Copy-Item -Path $KeyFile -Destination $TargetKey -Force
    icacls $TargetKey /inheritance:r /grant:r "$env:USERNAME`:F" | Out-Null
}

if (-not (Test-Path $TargetKey)) {
    Write-Host "ERROR: Key not found at $TargetKey" -ForegroundColor Red
    exit 1
}

$pub = & ssh-keygen -y -f $TargetKey 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Could not read public key from $TargetKey" -ForegroundColor Red
    Write-Host $pub
    exit 1
}
if ($pub -notmatch [regex]::Escape($ExpectedPubFragment)) {
    Write-Host "ERROR: Key does not match the deploy key authorized on the VPS."
    Write-Host "Use the private key from Hetzner setup — do not run ssh-keygen for a new pair."
    exit 1
}
Set-Content -Path "$TargetKey.pub" -Value $pub.Trim() -NoNewline
Write-Host "Deploy SSH key OK: $TargetKey" -ForegroundColor Green
