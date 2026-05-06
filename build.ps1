# Build launcher.exe + odoo_counter.exe และจัดวางใน dist_release/
# Usage:  .\build.ps1 1.0.0

param([string]$Version = "0.0.0")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$RELEASE = "dist_release"

Write-Host "→ cleaning build/ dist/ $RELEASE/"
Remove-Item -Recurse -Force build, dist, $RELEASE -ErrorAction SilentlyContinue

# ── 1) Build main app (onedir, no console) ─────────────────────
Write-Host "→ building odoo_counter.exe (this takes a few minutes)"
pyinstaller --noconsole --onedir --name odoo_counter `
    --collect-all ultralytics `
    --collect-all PyQt6 `
    --collect-all cv2 `
    odoo_counter_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (app) failed" }

# ── 2) Build launcher (onefile, no console — เล็กกว่า) ─────────
Write-Host "→ building launcher.exe"
pyinstaller --noconsole --onefile --name launcher launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (launcher) failed" }

# ── 3) Assemble release folder ────────────────────────────────
Write-Host "→ assembling $RELEASE/"
New-Item -ItemType Directory -Path $RELEASE | Out-Null
New-Item -ItemType Directory -Path "$RELEASE/app" | Out-Null

Copy-Item -Recurse "dist/odoo_counter/*" "$RELEASE/app/"
Copy-Item ai_3g_v5.pt "$RELEASE/app/"
Copy-Item "ถูก.mp3" "$RELEASE/app/"
Copy-Item "ผิด.mp3" "$RELEASE/app/"
Copy-Item dist/launcher.exe "$RELEASE/launcher.exe"

$Version | Out-File -Encoding utf8 -NoNewline "$RELEASE/app/version.txt"

Write-Host ""
Write-Host "✓ Built $RELEASE/  (version $Version)" -ForegroundColor Green
Write-Host "  → ทดสอบ: รัน $RELEASE\launcher.exe"
