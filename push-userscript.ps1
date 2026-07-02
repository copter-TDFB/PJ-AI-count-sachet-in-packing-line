# push-userscript.ps1
# พิมพ์คำสั่งเดียว: bump @version + commit + rebase + push เฉพาะ combined-auto-print.user.js
#
# วิธีใช้:
#   .\push-userscript.ps1            -> bump เลขท้ายอัตโนมัติ (2.2 -> 2.3) แล้ว push
#   .\push-userscript.ps1 2.5        -> ตั้ง version เป็น 2.5 เอง แล้ว push

param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$file = "combined-auto-print.user.js"

if (-not (Test-Path $file)) {
    Write-Host "ERROR: ไม่เจอไฟล์ $file (ต้องรันในโฟลเดอร์โปรเจกต์)" -ForegroundColor Red
    exit 1
}

# --- อ่าน @version ปัจจุบัน ---
$content = Get-Content $file -Raw -Encoding UTF8
$match = [regex]::Match($content, '(?m)^//\s*@version\s+([\d\.]+)')
if (-not $match.Success) {
    Write-Host "ERROR: หาบรรทัด @version ในไฟล์ไม่เจอ" -ForegroundColor Red
    exit 1
}
$current = $match.Groups[1].Value

# --- คำนวณ version ใหม่ ---
if ($Version -ne "") {
    $new = $Version
} else {
    $parts = $current.Split('.')
    $parts[-1] = [int]$parts[-1] + 1   # bump เลขท้าย
    $new = $parts -join '.'
}

Write-Host "Version: $current -> $new" -ForegroundColor Cyan

# --- เขียน @version ใหม่กลับลงไฟล์ ---
$updated = [regex]::Replace($content, '(?m)^(//\s*@version\s+)[\d\.]+', "`${1}$new")
[System.IO.File]::WriteAllText((Resolve-Path $file), $updated, (New-Object System.Text.UTF8Encoding($false)))

# --- git: add เฉพาะไฟล์นี้ + commit + rebase + push ---
git add $file
git commit -m "chore: bump userscript to v$new"
git fetch origin
git rebase origin/main
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "PUSH OK -> v$new ขึ้น GitHub แล้ว" -ForegroundColor Green
    Write-Host "เครื่องลูกกด Tampermonkey -> Check for userscript updates ได้เลย" -ForegroundColor Green
} else {
    Write-Host "push มีปัญหา ดู error ข้างบน" -ForegroundColor Red
}
