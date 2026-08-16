$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker wurde nicht gefunden. Bitte Docker Desktop installieren und starten.'
}

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Host 'Lokale .env wurde aus .env.example erstellt.' -ForegroundColor Green
}

$ipConfig = Get-NetIPConfiguration | Where-Object {
    $_.IPv4DefaultGateway -and $_.IPv4Address -and $_.NetAdapter.Status -eq 'Up'
} | Select-Object -First 1
$lanIp = if ($ipConfig) { $ipConfig.IPv4Address.IPAddress } else { $null }

docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose konnte nicht gestartet werden.' }

Write-Host ''
Write-Host 'Local Price Checks läuft.' -ForegroundColor Green
Write-Host 'Laptop:    http://localhost:8000'
if ($lanIp) {
    Write-Host "Smartphone: http://$lanIp`:8000"
    Write-Host 'Smartphone und Laptop müssen im selben WLAN/LAN sein.'
} else {
    Write-Warning 'LAN-IP konnte nicht automatisch ermittelt werden. Nutze ipconfig und öffne http://<IPv4>:8000.'
}
Write-Host ''
Write-Host 'Hinweis: Über HTTP funktionieren alle MVP-Funktionen außer ggf. der Handykamera. Für Kamera-Tests scripts/start-local-https.ps1 verwenden.' -ForegroundColor Yellow
Start-Process 'http://localhost:8000'
