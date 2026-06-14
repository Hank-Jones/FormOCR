# Copy project assets/ into src-tauri/resources for bundling (no download).

param(

    [switch]$AllowDownload,

    [switch]$Force

)



$ErrorActionPreference = "Stop"

. "$PSScriptRoot\lib-formocr.ps1"



$Root = Split-Path -Parent $PSScriptRoot

$Assets = "$Root\assets"

$AssetsOllamaExe = "$Assets\ollama\ollama.exe"

$AssetsOllama = "$Assets\models\ollama"

$AssetsApi = "$Assets\api-server"



$TauriDir = "$Root\apps\desktop\src-tauri"

$ResDir = "$TauriDir\resources"

$SeedOllama = "$ResDir\seed\ollama"

$SeedPaddle = "$ResDir\seed\paddle"

$ResBin = "$ResDir\binaries"



Write-Host "=== Prepare installer from assets/ (qwen2.5vl:3b only) ===" -ForegroundColor Cyan



# Release any lock on ollama.exe before copying (tray app respawns the server, kill it first)

$ollamaTray = Get-Process -Name "ollama app" -ErrorAction SilentlyContinue

if ($ollamaTray) {

    Write-Host "Stopping Ollama tray app (PID $($ollamaTray.Id)) so it stops respawning..."

    $ollamaTray | Stop-Process -Force

    Start-Sleep -Milliseconds 800

}

$ollamaProcs = Get-Process -Name "ollama" -ErrorAction SilentlyContinue

if ($ollamaProcs) {

    Write-Host "Stopping $($ollamaProcs.Count) ollama.exe process(es) to release file lock..."

    $ollamaProcs | Stop-Process -Force

    Start-Sleep -Milliseconds 1200

}



if ($AllowDownload) {

    & "$Root\scripts\populate-assets.ps1" -AllowDownload @($(if ($Force) { "-Force" }))

} elseif (-not (Test-Path "$Assets\manifest.json")) {

    Write-Host "assets/ not populated yet - filling from local machine ..."

    & "$Root\scripts\populate-assets.ps1" @($(if ($Force) { "-Force" }))

}



foreach ($pair in @(

        @{ Label = "ollama.exe"; Path = $AssetsOllamaExe },

        @{ Label = "qwen2.5vl:3b (vision OCR)"; Path = $AssetsOllama },

        @{ Label = "api-server"; Path = "$AssetsApi\api-server.exe" }

    )) {

    if (-not (Test-Path $pair.Path)) {

        throw "Missing assets/$($pair.Label) at $($pair.Path). Run: npm run populate:assets"

    }

}



New-Item -ItemType Directory -Path $ResDir, "$ResDir\seed", $ResBin -Force | Out-Null



# Offline bundle no longer ships Paddle weights (vision OCR only).

if (Test-Path $SeedPaddle) {

    Write-Host "Removing stale resources/seed/paddle (not bundled in offline build) ..."

    Remove-Item -Recurse -Force $SeedPaddle

}



$visionModels = Get-FormOcrDefaultOllamaModels
$ollamaPullSrc = "$env:USERPROFILE\.ollama\models"

Write-Host "Ensuring assets/models/ollama is vision-only (qwen2.5vl:3b) ..."
Repair-FormOcrOllamaVisionSeed -ModelsDir $AssetsOllama -SrcRoot $ollamaPullSrc -AllowedModels $visionModels

$needSeed = $Force -or -not (Test-FormOcrDirHasFiles $SeedOllama)
if (-not $needSeed) {
    try {
        Assert-FormOcrOllamaSeedVisionOnly -ModelsDir $SeedOllama -AllowedModels $visionModels
    } catch {
        $needSeed = $true
    }
}

if ($needSeed) {
    Copy-FormOcrOllamaSeed $AssetsOllama $SeedOllama $visionModels
    Assert-FormOcrOllamaSeedVisionOnly -ModelsDir $SeedOllama -AllowedModels $visionModels
} else {
    Write-Host "seed/ollama exists (use -Force to refresh)"
}



# Binaries for Tauri resources (refresh if -Force or bundle incomplete)

$ApiDst = "$ResBin\api-server"

$OllamaDst = "$ResBin\ollama.exe"

Assert-FormOcrApiBundle -ApiRoot $AssetsApi

$refreshApi = $Force -or -not (Test-FormOcrApiBundle $ApiDst)

if (-not $refreshApi -and (Test-Path "$AssetsApi\api-server.exe") -and (Test-Path "$ApiDst\api-server.exe")) {

    $refreshApi = (Get-Item "$AssetsApi\api-server.exe").LastWriteTimeUtc -gt `

        (Get-Item "$ApiDst\api-server.exe").LastWriteTimeUtc

}

if ($refreshApi) {

    Write-Host "Copying api-server into resources/binaries ..."

    Copy-FormOcrApiBundle -SourceApi $AssetsApi -DestApi $ApiDst

} else {

    Write-Host "resources/binaries/api-server up to date"

}

Copy-FormOcrOllamaBundle -SourceExe $AssetsOllamaExe -DestDir $ResBin



# Keep src-tauri/binaries in sync for build-api path

$BinDir = "$TauriDir\binaries"

New-Item -ItemType Directory -Path $BinDir -Force | Out-Null

Copy-FormOcrOllamaBundle -SourceExe $AssetsOllamaExe -DestDir $BinDir

Copy-FormOcrApiBundle -SourceApi $AssetsApi -DestApi "$BinDir\api-server"



$totalMb = [math]::Round((Get-ChildItem $ResDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 0)

Write-Host "`n=== resources ready ($($totalMb) MB) ===" -ForegroundColor Green

Write-Host "Next: npm run build:installer  (includes API build + this step unless -SkipPrepare)"

