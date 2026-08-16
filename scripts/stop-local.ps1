$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

docker compose -f docker-compose.yml -f docker-compose.https.yml down
if ($LASTEXITCODE -ne 0) {
    docker compose down
}
Write-Host 'Local Price Checks wurde gestoppt.' -ForegroundColor Green
