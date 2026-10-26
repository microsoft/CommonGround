$ErrorActionPreference = "Stop"
$parentPython = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv\Scripts\python.exe"
$python = "python"
if (-not $env:VIRTUAL_ENV -and (Test-Path -LiteralPath $parentPython)) {
    $python = $parentPython
}

& $python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Ready: $python"
Write-Host "Run .\run.ps1 from $PSScriptRoot, or python run.py with your environment active."