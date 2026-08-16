param(
    [Parameter(Mandatory=$true)][string]$RewePdf,
    [Parameter(Mandatory=$true)][string]$NettoPdf,
    [Parameter(Mandatory=$true)][string]$AldiPdf,
    [string]$TestDate = ""
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

foreach ($path in @($RewePdf,$NettoPdf,$AldiPdf)) {
    if (-not (Test-Path $path)) { throw "PDF nicht gefunden: $path" }
}

if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
if ($TestDate) {
    try { [datetime]::ParseExact($TestDate, 'yyyy-MM-dd', $null) | Out-Null }
    catch { throw 'TestDate muss YYYY-MM-DD sein, z. B. 2026-08-15.' }
    $envText = Get-Content '.env' -Raw
    if ($envText -match '(?m)^LOCAL_DATE_OVERRIDE=.*$') {
        $envText = [regex]::Replace($envText, '(?m)^LOCAL_DATE_OVERRIDE=.*$', "LOCAL_DATE_OVERRIDE=$TestDate")
    } else {
        $envText += "`r`nLOCAL_DATE_OVERRIDE=$TestDate`r`n"
    }
    Set-Content '.env' $envText -Encoding UTF8
    Write-Host "Lokales Testdatum: $TestDate" -ForegroundColor Yellow
}

New-Item -ItemType Directory -Force 'data\import' | Out-Null
$reweTarget = Join-Path (Resolve-Path 'data\import') 'rewe.pdf'
$nettoTarget = Join-Path (Resolve-Path 'data\import') 'netto.pdf'
$aldiTarget = Join-Path (Resolve-Path 'data\import') 'aldi.pdf'
Copy-Item $RewePdf $reweTarget -Force
Copy-Item $NettoPdf $nettoTarget -Force
Copy-Item $AldiPdf $aldiTarget -Force

docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Docker-App konnte nicht gestartet werden.' }

docker compose exec app python scripts/import_local_pdfs.py --rewe /app/data/import/rewe.pdf --netto /app/data/import/netto.pdf --aldi /app/data/import/aldi.pdf
if ($LASTEXITCODE -ne 0) { throw 'PDF-Import ist fehlgeschlagen.' }

Write-Host ''
Write-Host 'Lokale Prospekte wurden importiert.' -ForegroundColor Green
Write-Host 'Öffne http://localhost:8000/datenstatus und anschließend Meine Märkte/Favoriten/Angebote.'
if ($TestDate) { Write-Host 'Vor Live-Tests LOCAL_DATE_OVERRIDE in .env wieder leeren.' -ForegroundColor Yellow }
