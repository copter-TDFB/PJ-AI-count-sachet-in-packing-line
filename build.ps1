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
    --collect-all websockets `
    --exclude-module PySide6 `
    --exclude-module PyQt5 `
    --exclude-module shiboken6 `
    odoo_counter_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (app) failed" }

# ---- 2) Build launcher (onefile, no console) ----
# bundle truststore + certifi เพื่อให้ verify SSL บนเครื่อง user ได้ (แก้ CERTIFICATE_VERIFY_FAILED)
Write-Host "==> building launcher.exe"
python -m PyInstaller --noconsole --onefile --name launcher `
    --hidden-import truststore `
    --collect-all certifi `
    launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (launcher) failed" }

# ---- 3) Assemble release folder ----
Write-Host "==> assembling $RELEASE/"
New-Item -ItemType Directory -Path $RELEASE | Out-Null
New-Item -ItemType Directory -Path "$RELEASE/app" | Out-Null

Copy-Item -Recurse "dist/odoo_counter/*" "$RELEASE/app/"
Copy-Item ai_3g_v12.pt "$RELEASE/app/"
# Pre-exported OpenVINO model — saves ~30s startup time and avoids export-in-exe failures
if (Test-Path "ai_3g_v12_openvino_model") {
    Copy-Item -Recurse "ai_3g_v12_openvino_model" "$RELEASE/app/"
} else {
    Write-Host "WARNING: ai_3g_v12_openvino_model not found - app will fall back to .pt" -ForegroundColor Yellow
}
Get-ChildItem -Filter "*.mp3" | Copy-Item -Destination "$RELEASE/app/"
Copy-Item dist/launcher.exe "$RELEASE/launcher.exe"

# Bundle a portable SumatraPDF.exe for invoice auto-print (KAN-47) so target machines need
# zero setup — _default_sumatra_path() in odoo_counter_app.py prefers app/SumatraPDF/SumatraPDF.exe
# over the C:\Program Files\... fallback whenever it's present.
$SumatraCandidates = @(
    "$env:ProgramFiles\SumatraPDF",
    "${env:ProgramFiles(x86)}\SumatraPDF",
    "$env:LOCALAPPDATA\SumatraPDF"
)
$SumatraSrc = $SumatraCandidates | Where-Object { Test-Path "$_\SumatraPDF.exe" } | Select-Object -First 1
if ($SumatraSrc) {
    Write-Host "==> bundling SumatraPDF from $SumatraSrc"
    New-Item -ItemType Directory -Path "$RELEASE/app/SumatraPDF" | Out-Null
    # SumatraPDF 3.6+ แยก render engine ออกเป็น libmupdf.dll ที่วางคู่กับ exe — ถ้า copy ไปแค่
    # SumatraPDF.exe ไฟล์เดียว มันจะ exit 0 เงียบ ๆ โดยไม่พิมพ์อะไร (check=True เลยไม่ throw
    # แอปจึงขึ้น "พิมพ์ใบเสร็จแล้ว" ทั้งที่ไม่มีอะไรออก) — copy .exe + .dll ทั้งโฟลเดอร์แทน
    Get-ChildItem $SumatraSrc -File |
        Where-Object { $_.Extension -in '.exe', '.dll' } |
        Copy-Item -Destination "$RELEASE/app/SumatraPDF/"
    if (-not (Test-Path "$RELEASE/app/SumatraPDF/libmupdf.dll")) {
        Write-Host "WARNING: libmupdf.dll not found next to SumatraPDF.exe - test that app\SumatraPDF\SumatraPDF.exe runs on a machine without SumatraPDF installed" -ForegroundColor Yellow
    }
    Get-ChildItem "$RELEASE/app/SumatraPDF" -File | ForEach-Object {
        Write-Host ("    + {0} ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB))
    }
} else {
    Write-Host "WARNING: SumatraPDF.exe not found on this machine - invoice auto-print will need it installed on target machines" -ForegroundColor Yellow
}

# Out-File -Encoding utf8 ของ PowerShell 5.1 ใส่ BOM (﻿) ทำให้ parse_version พัง — ใช้ API ตรงเขียน UTF-8 no-BOM
[System.IO.File]::WriteAllText("$PSScriptRoot\$RELEASE\app\version.txt", $Version, (New-Object System.Text.UTF8Encoding $false))

Write-Host ""
Write-Host "OK - Built $RELEASE/  (version $Version)" -ForegroundColor Green
Write-Host "    Test by running: $RELEASE\launcher.exe"
