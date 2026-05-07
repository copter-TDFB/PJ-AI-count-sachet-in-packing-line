# Build launcher.exe + odoo_counter.exe and assemble dist_release/
# Usage:  .\build.ps1 1.0.0

param([string]$Version = "0.0.0")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$RELEASE = "dist_release"

Write-Host "==> cleaning build/ dist/ $RELEASE/"
Remove-Item -Recurse -Force build, dist, $RELEASE -ErrorAction SilentlyContinue

# ---- 1) Build main app (onedir, no console) ----
Write-Host "==> building odoo_counter.exe (this takes a few minutes)"
python -m PyInstaller --noconsole --onedir --name odoo_counter `
    --collect-all ultralytics `
    --collect-all PyQt6 `
    --collect-all cv2 `
    --collect-all openvino `
    --exclude-module PySide6 `
    --exclude-module PyQt5 `
    --exclude-module shiboken6 `
    odoo_counter_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (app) failed" }

# ---- 2) Build launcher (onefile, no console) ----
Write-Host "==> building launcher.exe"
python -m PyInstaller --noconsole --onefile --name launcher launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (launcher) failed" }

# ---- 3) Assemble release folder ----
Write-Host "==> assembling $RELEASE/"
New-Item -ItemType Directory -Path $RELEASE | Out-Null
New-Item -ItemType Directory -Path "$RELEASE/app" | Out-Null

Copy-Item -Recurse "dist/odoo_counter/*" "$RELEASE/app/"
Copy-Item ai_3g_v5.pt "$RELEASE/app/"
# Pre-exported OpenVINO model — saves ~30s startup time and avoids export-in-exe failures
if (Test-Path "ai_3g_v5_openvino_model") {
    Copy-Item -Recurse "ai_3g_v5_openvino_model" "$RELEASE/app/"
} else {
    Write-Host "WARNING: ai_3g_v5_openvino_model not found - app will fall back to .pt" -ForegroundColor Yellow
}
Get-ChildItem -Filter "*.mp3" | Copy-Item -Destination "$RELEASE/app/"
Copy-Item dist/launcher.exe "$RELEASE/launcher.exe"

$Version | Out-File -Encoding utf8 -NoNewline "$RELEASE/app/version.txt"

Write-Host ""
Write-Host "OK - Built $RELEASE/  (version $Version)" -ForegroundColor Green
Write-Host "    Test by running: $RELEASE\launcher.exe"
