# PowerShell script to run the puzzle collaboration web app
# Usage: 
#   .\run_web_app.ps1              # Normal mode (manual role selection)
#   .\run_web_app.ps1 -Study       # Study mode (with consent form)
#   .\run_web_app.ps1 -Worker      # Human worker with AI helper
#   .\run_web_app.ps1 -Study -Worker  # Study mode as worker

param(
    [switch]$Study,
    [switch]$Worker,
    [switch]$Helper
)

Write-Host "Starting Puzzle Collaboration Web App..." -ForegroundColor Green
Write-Host ""

# Use the main repository .venv environment
$repoRoot = (Get-Item $PSScriptRoot).Parent.Parent.Parent.FullName
$venvPath = Join-Path $repoRoot ".venv"

if (-Not (Test-Path $venvPath)) {
    Write-Host "Virtual environment not found at $venvPath" -ForegroundColor Red
    Write-Host "Please create it with: python -m venv $venvPath" -ForegroundColor Yellow
    exit 1
}

Write-Host "Activating virtual environment at $venvPath..." -ForegroundColor Cyan
& "$venvPath\Scripts\Activate.ps1"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Starting web server..." -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Access the app at:" -ForegroundColor Yellow
Write-Host "  http://localhost:5000" -ForegroundColor White
Write-Host ""
Write-Host "Worker interface: http://localhost:5000/worker" -ForegroundColor Cyan
Write-Host "Helper interface: http://localhost:5000/helper" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Build command arguments
$pyArgs = @()
if ($Worker) { $pyArgs += "--worker" }
if ($Helper) { $pyArgs += "--helper" }
if ($Study) { $pyArgs += "--run_study" }

if ($Study) {
    Write-Host "Running in STUDY MODE (consent form enabled)" -ForegroundColor Magenta
}

# Run the Flask app
python web_app.py @pyArgs
