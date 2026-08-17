param(
    [string]$SourceRepo = "https://github.com/danielwauer-maker/price-radar-app-81-960e2446.git",
    [string]$SourceBranch = "main"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Target = Join-Path $RepoRoot "frontend-lovable-source"
$Temp = Join-Path ([System.IO.Path]::GetTempPath()) ("local-price-checks-lovable-" + [guid]::NewGuid().ToString("N"))

Write-Host "=== LOVABLE SOURCE SYNC ===" -ForegroundColor Cyan
Write-Host "Source: $SourceRepo ($SourceBranch)"
Write-Host "Target: $Target"

try {
    git clone --depth 1 --branch $SourceBranch $SourceRepo $Temp
    if ($LASTEXITCODE -ne 0) {
        throw "Git clone failed. Make sure Git Credential Manager/GitHub authentication can access the Lovable repository."
    }

    if (Test-Path $Target) {
        Get-ChildItem -LiteralPath $Target -Force | Remove-Item -Recurse -Force
    } else {
        New-Item -ItemType Directory -Path $Target | Out-Null
    }

    $excludeNames = @(".git", ".lovable", "node_modules", "dist")
    Get-ChildItem -LiteralPath $Temp -Force | ForEach-Object {
        if ($excludeNames -contains $_.Name) { return }
        if ($_.Name -eq ".env" -or $_.Name -like ".env.*") { return }
        Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
    }

    $sourceSha = (git -C $Temp rev-parse HEAD).Trim()
    $sourceInfo = @"
# Lovable frontend source

Controlled snapshot of:
`danielwauer-maker/price-radar-app-81-960e2446` (`$SourceBranch`)

Source commit: `$sourceSha`

This folder is design/frontend source only. The production backend, collectors,
database and Sparplan remain in the Local Price Checks application.

Excluded from the snapshot: `.git/`, `.env*`, `.lovable/`, `node_modules/`, `dist/`.
"@
    Set-Content -LiteralPath (Join-Path $Target "SOURCE.md") -Value $sourceInfo -Encoding UTF8

    Write-Host "`nLovable source synced successfully." -ForegroundColor Green
    Write-Host "Source commit: $sourceSha"
    Write-Host "Review with: git status --short frontend-lovable-source"
} finally {
    if (Test-Path $Temp) {
        Remove-Item -LiteralPath $Temp -Recurse -Force
    }
}
