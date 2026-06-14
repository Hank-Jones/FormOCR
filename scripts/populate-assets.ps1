# Copy ollama.exe, qwen2.5vl:3b, and api-server into project assets/ (no download).

param(

    [switch]$Force,

    [switch]$AllowDownload,

    [string[]]$OllamaModels = @("qwen2.5vl:3b")

)



$ErrorActionPreference = "Stop"

. "$PSScriptRoot\lib-formocr.ps1"



$OllamaModels = @($OllamaModels | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })



$Root = Split-Path -Parent $PSScriptRoot

$Assets = "$Root\assets"

$OllamaExeDst = "$Assets\ollama\ollama.exe"

$OllamaModelsDst = "$Assets\models\ollama"

$ApiDst = "$Assets\api-server"



Write-Host "=== Populate project assets/ (qwen2.5vl:3b only) ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Path "$Assets\ollama", "$Assets\models", $OllamaModelsDst, $ApiDst -Force | Out-Null



if ($AllowDownload) {

    & "$Root\scripts\setup-offline.ps1"

}



# Ollama binary

$ollamaSrc = Get-FormOcrOllamaExe

if (-not $ollamaSrc) {

    throw "ollama.exe not found. Install Ollama or place ollama.exe in assets\ollama\"

}

if ($Force -or -not (Test-Path $OllamaExeDst)) {

    Copy-FormOcrOllamaBundle -SourceExe $ollamaSrc -DestDir (Split-Path $OllamaExeDst -Parent)

    Write-Host "ollama.exe + lib/ -> $(Split-Path $OllamaExeDst -Parent)"

} elseif ($Force -or -not (Test-Path (Join-Path (Split-Path $OllamaExeDst -Parent) "lib\ollama"))) {

    Copy-FormOcrOllamaBundle -SourceExe $ollamaSrc -DestDir (Split-Path $OllamaExeDst -Parent)

    Write-Host "ollama lib/ (GPU) -> $(Split-Path $OllamaExeDst -Parent)"

} else {

    Write-Host "ollama.exe exists (use -Force to refresh)"

}



$OllamaModelsSrc = "$env:USERPROFILE\.ollama\models"

$hw = if ($env:FORMOCR_HANDWRITING_OCR_MODEL) { $env:FORMOCR_HANDWRITING_OCR_MODEL } else { "qwen2.5vl:3b" }

if ($OllamaModels -notcontains $hw) { $OllamaModels += $hw }

foreach ($m in $OllamaModels) {

    if (-not (Test-FormOcrOllamaModelPresent $OllamaModelsSrc $m)) {

        throw "Ollama model not found: $m. Run: ollama pull $m (once on a connected PC)"

    }

}



# Ollama models seed (qwen2.5vl:3b vision model for handwriting OCR)

if ($Force -or -not (Test-FormOcrDirHasFiles $OllamaModelsDst)) {

    Write-Host "Copying Ollama models into assets/models/ollama ..."

    Copy-FormOcrOllamaSeed $OllamaModelsSrc $OllamaModelsDst $OllamaModels
    Assert-FormOcrOllamaSeedVisionOnly -ModelsDir $OllamaModelsDst

} else {

    Write-Host "models/ollama exists - checking vision-only layout ..."
    Repair-FormOcrOllamaVisionSeed -ModelsDir $OllamaModelsDst -SrcRoot $OllamaModelsSrc -AllowedModels $OllamaModels

}



# API bundle

if ($Force -or -not (Test-Path "$ApiDst\api-server.exe")) {

    & "$Root\scripts\build-api.ps1"

    $apiBuilt = "$Root\apps\desktop\src-tauri\binaries\api-server"

    if (Test-Path $ApiDst) { Remove-Item -Recurse -Force $ApiDst }

    New-Item -ItemType Directory -Path $ApiDst -Force | Out-Null

    Copy-Item -Path "$apiBuilt\*" -Destination $ApiDst -Recurse -Force

    Write-Host "api-server -> $ApiDst"

} else {

    Write-Host "api-server exists (use -Force to refresh)"

}



# Drop legacy Paddle weights from assets if present

$paddleAssets = "$Assets\models\paddle"

if (Test-Path $paddleAssets) {

    Write-Host "Removing legacy assets/models/paddle (not used by offline bundle) ..."

    Remove-Item -Recurse -Force $paddleAssets

}



$mb = [math]::Round((Get-ChildItem $Assets -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 0)

@{

    version = "2.0.0"

    populated_at = (Get-Date).ToString("o")

    size_mb = $mb

    ocr_engine = "qwen"
    vision_only = $true
    text_llm_bundled = $false

    paths = @{

        ollama_exe = "assets/ollama/ollama.exe"

        ollama_models = "assets/models/ollama"

        api_server = "assets/api-server"

    }

} | ConvertTo-Json -Depth 4 | Set-Content "$Assets\manifest.json" -Encoding utf8



Write-Host ("`n=== assets/ ready ({0} MB) ===" -f $mb) -ForegroundColor Green

Write-Host "Copy the whole FormOCR folder to another PC, then: npm run prepare:installer; npm run build:installer"

