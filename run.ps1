# CommonGround puzzle launcher (Windows PowerShell).
#
# Usage:
#   .\run.ps1 human-ai                 # human worker + AI helper
#   .\run.ps1 human-ai --role helper   # AI worker + human helper
#   .\run.ps1 human-human              # two humans (prints shared links)
#   .\run.ps1 ai-ai --limit 1          # headless AI vs AI
$ErrorActionPreference = 'Stop'
$py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
& $py run.py @args
