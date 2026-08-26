param(
    [string]$SourceRepo = "https://github.com/danielwauer-maker/price-radar-app-81-960e2446.git",
    [string]$SourceBranch = "main",
    [switch]$Apply
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

    $sourceSha = (git -C $Temp rev-parse HEAD).Trim()
    Write-Host "Source commit: $sourceSha"

    if (-not $Apply) {
        Write-Host "`nSAFE MODE: no files were changed." -ForegroundColor Yellow
        Write-Host "Lovable is not allowed to overwrite the production frontend without explicit approval."
        Write-Host "To apply a reviewed sync intentionally, run:"
        Write-Host "  .\scripts\sync-lovable-source.ps1 -Apply"
        return
    }

    Write-Host "`nAPPLY MODE: approved Lovable sync is being applied." -ForegroundColor Yellow

    $protectedRelativePaths = @(
        ".dockerignore",
        "Dockerfile.server",
        "public\brand",
        "public\favicon.ico",
        "public\manifest.webmanifest",
        "src\components\brand",
        "src\brand.css"
    )

    $ProtectedBackup = Join-Path ([System.IO.Path]::GetTempPath()) ("local-price-checks-branding-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $ProtectedBackup | Out-Null

    foreach ($relativePath in $protectedRelativePaths) {
        $sourcePath = Join-Path $Target $relativePath
        if (Test-Path $sourcePath) {
            $backupPath = Join-Path $ProtectedBackup $relativePath
            $backupParent = Split-Path $backupPath -Parent
            New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
            Copy-Item -LiteralPath $sourcePath -Destination $backupPath -Recurse -Force
        }
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

    foreach ($relativePath in $protectedRelativePaths) {
        $backupPath = Join-Path $ProtectedBackup $relativePath
        if (Test-Path $backupPath) {
            $destinationPath = Join-Path $Target $relativePath
            $destinationParent = Split-Path $destinationPath -Parent
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
            if (Test-Path $destinationPath) {
                Remove-Item -LiteralPath $destinationPath -Recurse -Force
            }
            Copy-Item -LiteralPath $backupPath -Destination $destinationPath -Recurse -Force
        }
    }

    $sourceInfo = @"
# Lovable frontend source

Controlled snapshot of:
`danielwauer-maker/price-radar-app-81-960e2446` (`$SourceBranch`)

Source commit: `$sourceSha`

This folder is design/frontend source only. The production backend, collectors,
database and Sparplan remain in the Local Price Checks application.

Excluded from the snapshot: `.git/`, `.env*`, `.lovable/`, `node_modules/`, `dist/`.
Protected Spareno branding preserved by the sync: `public/brand/`, `public/favicon.ico`,
`public/manifest.webmanifest`, `src/components/brand/`, `src/brand.css`.

The sync is safe-mode by default and only writes files when explicitly invoked with `-Apply`.
"@
    Set-Content -LiteralPath (Join-Path $Target "SOURCE.md") -Value $sourceInfo -Encoding UTF8

    Write-Host "`nLovable source synced successfully." -ForegroundColor Green
    Write-Host "Source commit: $sourceSha"
    Write-Host "Review with: git status --short frontend-lovable-source"
} finally {
    if (Test-Path $Temp) {
        Remove-Item -LiteralPath $Temp -Recurse -Force
    }
    if ($ProtectedBackup -and (Test-Path $ProtectedBackup)) {
        Remove-Item -LiteralPath $ProtectedBackup -Recurse -Force
    }
}
