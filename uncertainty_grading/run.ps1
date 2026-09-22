param(
    [switch]$Production,
    [string]$HostName,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$python = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Parent CommonGround .venv not found. Create it before running the app."
}

$arguments = @("-m", "uncertainty_grading", "serve")
if ($Production) { $arguments += "--production" }
if ($HostName) { $arguments += @("--host", $HostName) }
if ($Port -gt 0) { $arguments += @("--port", $Port) }

Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & $python @arguments
}
finally {
    Pop-Location
}