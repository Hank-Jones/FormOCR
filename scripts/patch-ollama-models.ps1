# Copy missing Ollama models (qwen2.5vl:3b, etc.) from installer seed into FormOCR AppData.
param(
    [string]$SeedDir = "",
    [string]$DestDir = "$env:LOCALAPPDATA\FormOCR\models\ollama"
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib-formocr.ps1"

if (-not $SeedDir) {
    foreach ($c in @(
            "$env:LOCALAPPDATA\Programs\FormOCR\seed\ollama",
            (Join-Path (Split-Path -Parent $PSScriptRoot) "dist\FormOCR-Offline\app\seed\ollama")
        )) {
        if (Test-FormOcrDirHasFiles $c) {
            $SeedDir = $c
            break
        }
    }
}
if (-not $SeedDir -or -not (Test-Path $SeedDir)) {
    throw @"
No Ollama seed found. Install FormOCR first, or pass -SeedDir to a folder with manifests/blobs.

On a dev PC with models: ollama pull qwen2.5vl:3b
  npm run populate:assets -- -Force -OllamaModels "qwen2.5vl:3b"
"@
}

Write-Host "=== Patch FormOCR Ollama models ===" -ForegroundColor Cyan
Write-Host "  seed: $SeedDir"
Write-Host "  dest: $DestDir"
Stop-FormOcrLockingProcesses
Sync-FormOcrOllamaModelsToAppData -SourceRoot $SeedDir -DestRoot $DestDir

Write-Host "`nVerify:" -ForegroundColor Cyan
foreach ($m in (Get-FormOcrDefaultOllamaModels)) {
    $ok = Test-FormOcrOllamaModelPresent $DestDir $m
    $color = if ($ok) { "Green" } else { "Yellow" }
    Write-Host "  $m : $(if ($ok) { 'OK' } else { 'MISSING' })" -ForegroundColor $color
}

Write-Host "`nQuit FormOCR completely, then launch again so Ollama reloads models." -ForegroundColor Green
