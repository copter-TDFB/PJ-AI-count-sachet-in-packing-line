# Build -> zip -> upload as GitHub Release
# Prereq: gh CLI installed and logged in (gh auth login)
# Usage:  .\release.ps1 1.0.1 "fix barcode bug"

param(
    [Parameter(Mandatory=$true)][string]$Version,
    [string]$Notes = "Auto-update release"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Refresh PATH from registry so gh CLI is found even in stale sessions
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

# 1) build
& .\build.ps1 $Version

# 2) zip the app/ folder (launcher fetches this)
# Use bsdtar (built-in on Windows 10+) - much faster than Compress-Archive for large folders
$ZipName = "odoo-counter-$Version.zip"
Write-Host "==> zipping -> $ZipName (via tar)"
Remove-Item $ZipName -ErrorAction SilentlyContinue
tar -caf $ZipName -C dist_release app
if ($LASTEXITCODE -ne 0) { throw "tar zip failed" }
$ZipMB = [math]::Round((Get-Item $ZipName).Length/1MB, 1)
Write-Host "    zip size: $ZipMB MB"

# 3) create GitHub release via gh CLI
Write-Host "==> uploading release v$Version"
gh release create "v$Version" $ZipName --title "v$Version" --notes "$Notes"
if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }

Write-Host ""
Write-Host "OK - Released v$Version" -ForegroundColor Green
Write-Host "    Clients with launcher.exe will auto-update on next launch."
