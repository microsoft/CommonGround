$ErrorActionPreference = "Stop"
$python = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Parent CommonGround .venv not found. Create it before running doctor."
}

Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & $python -m uncertainty_grading doctor
}
finally {
    Pop-Location
}