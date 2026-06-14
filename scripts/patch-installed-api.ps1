# Copy the newest api-server bundle into the installed FormOCR app (no full reinstall).
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\FormOCR"
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib-formocr.ps1"
$Root = Split-Path -Parent $PSScriptRoot

$source = Get-FormOcrApiSource -Root $Root
$dest = Join-Path $InstallDir "binaries\api-server"
if (-not (Test-Path (Join-Path $InstallDir "formocr-desktop.exe"))) {
    throw "FormOCR is not installed at $InstallDir. Run FormOCR-Setup.cmd first."
}

Write-Host "Patching installed API" -ForegroundColor Cyan
Write-Host "  from: $source"
Write-Host "  to:   $dest"
Stop-FormOcrLockingProcesses
Copy-FormOcrApiBundle -SourceApi $source -DestApi $dest
$stamp = Join-Path $dest "FORMOCR_API_BUILD.txt"
if (Test-Path $stamp) {
    Write-Host "  build: $((Get-Content $stamp -Raw).Trim())" -ForegroundColor Green
}
Write-Host "`nDone. Quit FormOCR completely, then launch again." -ForegroundColor Green
