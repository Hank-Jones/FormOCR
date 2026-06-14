# Copy a freshly built api-server into dist\FormOCR-Offline (fixes stale CppSupport / paddleocr bundle).
param(
    [string]$SourceApi = "",
    [string[]]$DistFolders = @("FormOCR-Offline", "FormOCR-Offline.new", "FormOCR-Offline.staging")
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib-formocr.ps1"
$Root = Split-Path -Parent $PSScriptRoot

if (-not $SourceApi) {
    $SourceApi = Get-FormOcrApiSource -Root $Root
}
if (-not $SourceApi -or -not (Test-FormOcrApiBundle $SourceApi)) {
    throw "No valid api-server bundle found. Run: .\scripts\build-api.ps1"
}
$stamp = Get-FormOcrApiSourceStamp $SourceApi
Write-Host "  build stamp: $(if ($stamp -eq [datetime]::MinValue) { 'unknown' } else { $stamp.ToString('yyyy-MM-dd HH:mm:ss UTC') })" -ForegroundColor DarkGray

Write-Host "Source API bundle: $SourceApi" -ForegroundColor Cyan
$distRoot = Join-Path $Root "dist"
foreach ($name in $DistFolders) {
    $appApi = Join-Path $distRoot "$name\app\binaries\api-server"
    if (-not (Test-Path (Split-Path $appApi -Parent))) { continue }
    Write-Host "Updating $appApi ..."
    Stop-FormOcrLockingProcesses
    if (Test-Path $appApi) {
        Remove-FormOcrPathForce $appApi | Out-Null
        if (Test-Path $appApi) { throw "Cannot remove locked $appApi" }
    }
    Copy-FormOcrApiBundle -SourceApi $SourceApi -DestApi $appApi
    Write-Host "  OK" -ForegroundColor Green
}

foreach ($name in $DistFolders) {
    $folder = Join-Path $distRoot $name
    if (-not (Test-Path $folder)) { continue }
    Copy-Item "$Root\scripts\lib-formocr.ps1" (Join-Path $folder "lib-formocr.ps1") -Force
    Copy-Item "$Root\scripts\install-formocr.ps1" (Join-Path $folder "install-formocr.ps1") -Force
    Copy-Item "$Root\scripts\FormOCR-Setup.cmd" (Join-Path $folder "FormOCR-Setup.cmd") -Force -ErrorAction SilentlyContinue
}

Write-Host "`nDone. Run FormOCR-Setup.cmd from dist\FormOCR-Offline (or .new)." -ForegroundColor Green
