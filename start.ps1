# start.ps1 — Start all dev processes (Flask + Celery worker)
# Usage: .\start.ps1
# Requires: pip install honcho (included in backend/requirements.txt)

Set-Location $PSScriptRoot

# Activate virtual environment if present
if (Test-Path ".\backend\venv\Scripts\Activate.ps1") {
    . .\backend\venv\Scripts\Activate.ps1
} elseif (Test-Path ".\venv\Scripts\Activate.ps1") {
    . .\venv\Scripts\Activate.ps1
}

# Run all processes defined in Procfile
honcho start
