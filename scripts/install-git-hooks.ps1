# Point this clone at the versioned hooks in .githooks/
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
git config core.hooksPath .githooks
Write-Host "core.hooksPath=$(git config --get core.hooksPath)"
Write-Host "Git hooks installed. Pre-commit is slim (mapped tests); CI owns the full suite."
