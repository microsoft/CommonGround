$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $projectRoot ".venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Parent environment not found at $venv. Create CommonGround\.venv first."
}

& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
& $python -m pip install --editable $PSScriptRoot --no-deps

Get-ChildItem $PSScriptRoot -Recurse -Force -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
$eggInfo = Join-Path $PSScriptRoot "uncertainty_grading.egg-info"
if (Test-Path $eggInfo) {
    Remove-Item $eggInfo -Recurse -Force
}

Write-Host "Ready: $python"
Write-Host "Run .\run.ps1 or .\doctor.ps1 from $PSScriptRoot"