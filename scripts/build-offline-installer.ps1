# Full offline package: build-api -> prepare resources -> Tauri release -> dist\FormOCR-Offline
# Skips: -SkipApiBuild, -SkipPrepare, -SkipTauriBuild (for faster iteration when unchanged)
param(
    [switch]$SkipApiBuild,
    [switch]$SkipPrepare,
    [switch]$SkipTauriBuild,
    [switch]$BuildSetupExe
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib-formocr.ps1"
$Root = Split-Path -Parent $PSScriptRoot
$Desktop = "$Root\apps\desktop"
$TauriDir = "$Desktop\src-tauri"
$DistRoot = "$Root\dist\FormOCR-Offline"
$StagingRoot = "$Root\dist\FormOCR-Offline.staging"
$AppDir = "$StagingRoot\app"
$Version = "1.0.0"

Write-Host "=== FormOCR offline installer build ===" -ForegroundColor Cyan

if (-not $SkipApiBuild) {
    Write-Host "`n=== Build API (PyInstaller) ===" -ForegroundColor Yellow
    & "$Root\scripts\build-api.ps1"
    Sync-FormOcrApiToAssets -Root $Root
} else {
    Write-Host "`n=== Skipping API build (-SkipApiBuild) ===" -ForegroundColor DarkGray
}

if (-not $SkipPrepare) {
    Write-Host "`n=== Prepare installer assets ===" -ForegroundColor Yellow
    # -Force: refresh seed/ollama and api-server from assets/ (npm does not pass flags to ps1)
    & "$Root\scripts\prepare-installer-assets.ps1" -Force
} else {
    $seedOllama = "$TauriDir\resources\seed\ollama"
    if (-not (Test-Path $seedOllama)) {
        throw "Missing resources/seed/ollama. Run prepare-installer-assets.ps1 first."
    }
}

if (-not $SkipTauriBuild) {
    Write-Host "`n=== Tauri release build ===" -ForegroundColor Yellow
    $staleRes = "$TauriDir\target\release\resources"
    if (Test-Path $staleRes) {
        Write-Host "Removing stale $staleRes ..."
        Remove-Item -Recurse -Force $staleRes
    }
    Set-Location $Desktop
    if (-not (Test-Path node_modules)) { npm install }
    Write-Host "Regenerating app icons (embeds into .exe) ..."
    npm run icons
    # Force Windows resource rebuild when icon.ico changed (cargo may skip otherwise).
    Get-ChildItem "$TauriDir\target\release\build" -Filter "formocr-desktop-*" -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item (Join-Path $_.FullName "out\resource.rc") -Force -ErrorAction SilentlyContinue }
    Remove-Item "$TauriDir\target\release\formocr-desktop.exe" -Force -ErrorAction SilentlyContinue
    npm run build
    npm run tauri build -- --no-bundle
    Set-Location $Root
}

$ReleaseRoots = @(
    "$TauriDir\target\release",
    "$TauriDir\target\x86_64-pc-windows-msvc\release"
)
$MainExe = $null
foreach ($r in $ReleaseRoots) {
    if (-not (Test-Path $r)) { continue }
    $exe = Get-ChildItem -Path $r -Filter "formocr-desktop.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($exe) { $MainExe = $exe }
}
if (-not $MainExe) {
    throw "formocr-desktop.exe not found. Run tauri build."
}

$ResSrc = "$TauriDir\resources"
if (-not (Test-Path $ResSrc)) {
    throw "Missing $ResSrc - run prepare-installer-assets.ps1 first."
}

if (Test-Path $StagingRoot) {
    Remove-FormOcrPathForce $StagingRoot | Out-Null
    if (Test-Path $StagingRoot) {
        throw "Cannot clear $StagingRoot. Close FormOCR and any Explorer window on dist\, then retry."
    }
}
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null

Write-Host "`n=== Packaging app payload ===" -ForegroundColor Yellow
Copy-Item $MainExe.FullName "$AppDir\formocr-desktop.exe" -Force
$iconIco = "$TauriDir\icons\icon.ico"
if (Test-Path $iconIco) {
    Copy-Item $iconIco "$AppDir\FormOCR.ico" -Force
    Write-Host "Bundled FormOCR.ico for shortcuts"
}
# Tauri on Windows resolves Resource paths next to the exe (binaries/, seed/), not under resources/.
robocopy $ResSrc $AppDir /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Failed to copy bundled resources (robocopy exit $LASTEXITCODE)" }
Clear-RobocopyExitCode

$appApi = "$AppDir\binaries\api-server"
$apiExe = "$appApi\api-server.exe"
if (-not (Test-Path $apiExe)) {
    throw "Missing $apiExe. Run npm run build:installer (or prepare:installer without -SkipPrepare)."
}
# Always use the api-server built in this run (resources copy may be an older complete bundle).
$assetsApi = "$Root\assets\api-server"
$fallbackApi = "$TauriDir\binaries\api-server"
$srcApi = if (Test-FormOcrApiBundle $assetsApi) { $assetsApi }
    elseif (Test-FormOcrApiBundle $fallbackApi) { $fallbackApi }
    else { $null }
if (-not $srcApi) {
    throw "No complete api-server bundle. Run npm run build:installer without -SkipApiBuild."
}
$refreshApi = -not $SkipApiBuild
if (-not $refreshApi -and (Test-Path "$srcApi\api-server.exe") -and (Test-Path "$appApi\api-server.exe")) {
    $srcT = (Get-Item "$srcApi\api-server.exe").LastWriteTimeUtc
    $dstT = (Get-Item "$appApi\api-server.exe").LastWriteTimeUtc
    if ($srcT -gt $dstT) {
        Write-Host "Source api-server is newer than packaged copy; refreshing ..."
        $refreshApi = $true
    }
}
if (-not (Test-FormOcrApiBundle $appApi)) {
    Write-Host "Packaged api-server incomplete; copying from assets ..."
    $refreshApi = $true
}
if ($refreshApi) {
    Write-Host "Refreshing packaged api-server from latest build ..."
    Stop-FormOcrLockingProcesses
    Copy-FormOcrApiBundle -SourceApi $srcApi -DestApi $appApi
}
Assert-FormOcrApiBundle -ApiRoot $appApi
Write-Host "Bundled API: $apiExe (bundle OK)" -ForegroundColor Green
Copy-Item "$Root\scripts\install-formocr.ps1" "$AppDir\install-formocr.ps1" -Force
Copy-Item "$Root\scripts\lib-formocr.ps1" "$AppDir\lib-formocr.ps1" -Force

Copy-Item "$Root\scripts\FormOCR-Setup.cmd" "$StagingRoot\FormOCR-Setup.cmd" -Force
Copy-Item "$Root\scripts\install-formocr.ps1" "$StagingRoot\install-formocr.ps1" -Force
Copy-Item "$Root\scripts\lib-formocr.ps1" "$StagingRoot\lib-formocr.ps1" -Force

$setupExe = $null
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($BuildSetupExe -and $iscc) {
    Write-Host "`n=== Building FormOCR-Setup.exe (Inno Setup) ===" -ForegroundColor Yellow
    $iss = "$Root\scripts\FormOCR-installer.iss"
    & $iscc "/DSourceRoot=$AppDir" $iss
    if ($LASTEXITCODE -eq 0) {
        $setupExe = Get-ChildItem "$StagingRoot\FormOCR-Setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    } else {
        Write-Host "Inno Setup compile failed; use FormOCR-Setup.cmd instead." -ForegroundColor Yellow
    }
} elseif ($BuildSetupExe) {
    Write-Host "Inno Setup not found - use FormOCR-Setup.cmd" -ForegroundColor Yellow
} else {
    Write-Host "Installer: FormOCR-Setup.cmd (use -BuildSetupExe to also build a large FormOCR-Setup.exe)" -ForegroundColor DarkGray
}

$readme = @'
FormOCR Offline Package
=======================

INSTALL
  Double-click FormOCR-Setup.cmd (or FormOCR-Setup.exe if built with Inno Setup).

  Installs to %LOCALAPPDATA%\Programs\FormOCR, seeds models, creates shortcuts.
  No manual configuration.

OFFLINE PC
  Copy the whole dist\FormOCR-Offline folder, then run FormOCR-Setup.cmd.

CONTENTS
  FormOCR-Setup.cmd / FormOCR-Setup.exe
  install-formocr.ps1, lib-formocr.ps1
  app\  (formocr-desktop.exe + binaries\ + seed\ next to exe)

MODELS (offline bundle)
  Vision OCR only: qwen2.5vl:3b via bundled Ollama.
  No text LLM (phi3/llama) for AI correction — that feature is disabled.

DATA: %LOCALAPPDATA%\FormOCR\
'@
$readme | Out-File -FilePath "$StagingRoot\README-OFFLINE.txt" -Encoding utf8

$PublishedRoot = Publish-FormOcrOfflineDistRoot -StagingRoot $StagingRoot -DistRoot $DistRoot

$distMb = [math]::Round((Get-ChildItem $PublishedRoot -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 0)
Write-Host ("`n=== Done: $PublishedRoot ({0} MB) ===" -f $distMb) -ForegroundColor Green
Write-Host "Installer: $PublishedRoot\FormOCR-Setup.cmd"
if ($setupExe) {
    $setupOut = Join-Path $PublishedRoot "FormOCR-Setup.exe"
    if (Test-Path $setupOut) {
        Write-Host "Setup EXE: $setupOut" -ForegroundColor Green
    }
}
