# Build → zip → upload เป็น GitHub Release
# Prereq: ติดตั้ง gh CLI แล้ว (https://cli.github.com) และ gh auth login เรียบร้อย
# Usage:  .\release.ps1 1.0.1 "fix barcode bug"

param(
    [Parameter(Mandatory=$true)][string]$Version,
    [string]$Notes = "Auto-update release"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# 1) build
& .\build.ps1 $Version

# 2) zip ตัว app/ (launcher จะดึงจากตรงนี้)
$ZipName = "odoo-counter-$Version.zip"
Write-Host "→ zipping → $ZipName"
Remove-Item $ZipName -ErrorAction SilentlyContinue
Compress-Archive -Path "dist_release/app" -DestinationPath $ZipName -Force

# 3) สร้าง release ผ่าน gh
Write-Host "→ uploading release v$Version"
gh release create "v$Version" $ZipName --title "v$Version" --notes "$Notes"
if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }

Write-Host ""
Write-Host "✓ Released v$Version" -ForegroundColor Green
Write-Host "  ลูกค้าที่มี launcher.exe จะ auto-update รอบหน้าที่เปิดโปรแกรม"
