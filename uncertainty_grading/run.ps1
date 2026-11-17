param(
    [switch]$Production,
    [switch]$Study,
    [string]$HostName,
    [int]$Port = 0,
    [ValidateSet("A", "B", "C", "D", "E")]
    [string]$Condition,
    [ValidateSet("CB", "CA")]
    [string]$Arm,
    [string]$Dialogue,
    [ValidateSet("source", "shared", "nonshared")]
    [string]$View
)

$ErrorActionPreference = "Stop"
$parentPython = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv\Scripts\python.exe"
$python = "python"
if (-not $env:VIRTUAL_ENV -and (Test-Path -LiteralPath $parentPython)) {
    $python = $parentPython
}

$arguments = @((Join-Path $PSScriptRoot "run.py"))
if ($Production) { $arguments += "--production" }
if ($Study) { $arguments += "--study" }
if ($HostName) { $arguments += @("--host", $HostName) }
if ($Port -gt 0) { $arguments += @("--port", $Port) }
if ($Condition) { $arguments += @("--condition", $Condition) }
if ($Arm) { $arguments += @("--arm", $Arm) }
if ($Dialogue) { $arguments += @("--dialogue", $Dialogue) }
if ($View) { $arguments += @("--view", $View) }

& $python @arguments
exit $LASTEXITCODE