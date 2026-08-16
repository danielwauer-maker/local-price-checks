$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker wurde nicht gefunden. Bitte Docker Desktop installieren und starten.'
}
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }

$ipConfig = Get-NetIPConfiguration | Where-Object {
    $_.IPv4DefaultGateway -and $_.IPv4Address -and $_.NetAdapter.Status -eq 'Up'
} | Select-Object -First 1
if (-not $ipConfig) { throw 'Keine aktive LAN/WLAN-Verbindung mit IPv4-Adresse gefunden.' }
$lanIp = $ipConfig.IPv4Address.IPAddress
$env:LOCAL_HOST = $lanIp

New-Item -ItemType Directory -Force '.local-dev' | Out-Null

docker compose -f docker-compose.yml -f docker-compose.https.yml up --build -d
if ($LASTEXITCODE -ne 0) { throw 'HTTPS-Docker-Stack konnte nicht gestartet werden.' }

Start-Sleep -Seconds 3
docker compose -f docker-compose.yml -f docker-compose.https.yml cp caddy:/data/caddy/pki/authorities/local/root.crt .local-dev/caddy-root.crt
if ($LASTEXITCODE -ne 0) { throw 'Lokales Caddy-Root-Zertifikat konnte nicht exportiert werden.' }

try {
    Import-Certificate -FilePath (Resolve-Path '.local-dev/caddy-root.crt') -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
    Write-Host 'Lokales HTTPS-Zertifikat wurde für den aktuellen Windows-Benutzer vertraut.' -ForegroundColor Green
} catch {
    Write-Warning 'Zertifikat konnte nicht automatisch in Windows installiert werden. Browser kann eine Zertifikatswarnung zeigen.'
}

Write-Host ''
Write-Host 'HTTPS-Test läuft.' -ForegroundColor Green
Write-Host "Laptop:     https://$lanIp`:8443"
Write-Host "Smartphone: https://$lanIp`:8443"
Write-Host ''
Write-Host 'Für die Kamera muss das lokale Root-Zertifikat auch auf dem Smartphone als vertrauenswürdig installiert werden:' -ForegroundColor Yellow
Write-Host (Resolve-Path '.local-dev/caddy-root.crt')
Write-Host 'Siehe docs/LOCAL_TESTING.md für iPhone/Android-Schritte.'
Start-Process "https://$lanIp`:8443"
