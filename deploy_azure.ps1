# Deploy to Azure Web App
# This script creates a clean deployment package excluding problematic files

param(
    [Parameter(Mandatory=$false)]
    [string]$AppName = "CommonGround",
    
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "CommonGround"
)

Write-Host "Creating clean deployment package..." -ForegroundColor Cyan

# Get script directory (puzzle folder)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Create temp directory for clean package
$tempDir = Join-Path $env:TEMP "azure_deploy_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
Write-Host "Temp directory: $tempDir" -ForegroundColor Gray

# Copy necessary files only
Write-Host "Copying application files..." -ForegroundColor Cyan

$itemsToCopy = @(
    "web_app.py",
    "puzzle_constants.py",
    "game_session.py",
    "requirements.txt",
    ".deployment",
    "startup.sh",
    "startup_minimal.sh",
    "run_web_app.sh",
    "routes.py",
    "socket_handlers.py",
    "templates",
    "static",
    "utils"
)

foreach ($item in $itemsToCopy) {
    $sourcePath = Join-Path $scriptDir $item
    if (Test-Path $sourcePath) {
        $destPath = Join-Path $tempDir $item
        Write-Host "  Copying: $item" -ForegroundColor Gray
        Copy-Item -Path $sourcePath -Destination $destPath -Recurse -Force
    }
}

# Copy ai.py if it exists (but not the whole agents folder)
$aiPath = Join-Path $scriptDir "ai.py"
if (Test-Path $aiPath) {
    Write-Host "  Copying: ai.py" -ForegroundColor Gray
    Copy-Item -Path $aiPath -Destination (Join-Path $tempDir "ai.py") -Force
}

# Copy web_logger.py if it exists
$loggerPath = Join-Path $scriptDir "web_logger.py"
if (Test-Path $loggerPath) {
    Write-Host "  Copying: web_logger.py" -ForegroundColor Gray
    Copy-Item -Path $loggerPath -Destination (Join-Path $tempDir "web_logger.py") -Force
}

# Create zip file
$zipPath = Join-Path $env:TEMP "azure_deploy.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Write-Host "Creating zip package..." -ForegroundColor Cyan
Compress-Archive -Path "$tempDir\*" -DestinationPath $zipPath -Force

$zipSize = (Get-Item $zipPath).Length / 1MB
Write-Host "Zip package created: $([math]::Round($zipSize, 2)) MB" -ForegroundColor Green

# Deploy to Azure
Write-Host "`nDeploying to Azure Web App: $AppName" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroup" -ForegroundColor Gray

try {
    az webapp deploy --resource-group $ResourceGroup --name $AppName --src-path $zipPath --type zip
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`nDeployment successful!" -ForegroundColor Green
        Write-Host "URL: https://$AppName.azurewebsites.net" -ForegroundColor Cyan
    } else {
        Write-Host "`nDeployment failed!" -ForegroundColor Red
    }
} catch {
    Write-Host "Error during deployment: $_" -ForegroundColor Red
}

# Cleanup
Write-Host "`nCleaning up..." -ForegroundColor Gray
Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

Write-Host "Done!" -ForegroundColor Green
