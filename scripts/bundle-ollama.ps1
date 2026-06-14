# Copy ollama.exe + lib/ (GPU runners) into Tauri binaries from local install (no download).
param([switch]$Force)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib-formocr.ps1"

$Root = Split-Path -Parent $PSScriptRoot
$BinDir = "$Root\apps\desktop\src-tauri\binaries"
$DestExe = "$BinDir\ollama.exe"
New-Item -ItemType Directory -Path $BinDir -Force | Out-Null

if (-not $Force -and (Test-Path $DestExe) -and (Test-Path "$BinDir\lib\ollama")) {
    Write-Host "Using existing Ollama bundle in $BinDir"
    return
}

$installed = Resolve-FormOcrOllamaExe -ExtraCandidates @(
    "$Root\apps\desktop\src-tauri\resources\binaries\ollama.exe"
)
if ($installed) {
    Copy-FormOcrOllamaBundle -SourceExe $installed -DestDir $BinDir
    Write-Host "Copied Ollama bundle from $installed -> $BinDir"
    return
}

throw @"
ollama.exe not found locally. Install Ollama to:
  $env:LOCALAPPDATA\Programs\Ollama\ollama.exe
Or place ollama.exe + lib/ in src-tauri/binaries/
(No download - use local copy only.)
"@
