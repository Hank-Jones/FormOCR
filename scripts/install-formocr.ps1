# Installs FormOCR offline: copies app, seeds models into AppData, creates shortcuts. No manual config.

param(

    [string]$SourceDir = "",

    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\FormOCR",

    [switch]$SeedOnly,

    [switch]$LaunchAfter

)



$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "lib-formocr.ps1")



if (-not $SourceDir) {

    $SourceDir = Join-Path $PSScriptRoot "app"

}

if (-not (Test-Path "$SourceDir\formocr-desktop.exe")) {

    throw "Missing $SourceDir\formocr-desktop.exe. Run this from the FormOCR-Offline folder or pass -SourceDir."

}



$dataRoot = Join-Path $env:LOCALAPPDATA "FormOCR"

$modelsRoot = Join-Path $dataRoot "models"

$ollamaDst = Join-Path $modelsRoot "ollama"

$marker = Join-Path $modelsRoot ".offline-seed-v1"



function Test-FormOcrDirHasFiles([string]$path) {

    if (-not (Test-Path $path)) { return $false }

    $files = Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue |

        Where-Object { $_.Name -ne '.gitkeep' }

    return $files.Count -gt 0

}



function Test-ModelsReady([string]$dst) {

    if (-not (Test-Path $dst)) { return $false }

    foreach ($m in (Get-FormOcrDefaultOllamaModels)) {

        if (-not (Test-FormOcrOllamaModelPresent $dst $m)) { return $false }

    }

    return $true

}



function Copy-OllamaSeedIfNeeded([string]$src, [string]$dst) {

    if (-not (Test-Path $src)) {

        Write-Host "  Skip Ollama models (not bundled)" -ForegroundColor DarkYellow

        return

    }

    if (Test-FormOcrOllamaNeedsRefresh $src $dst) {

        Write-Host "  Updating Ollama models (copying missing qwen2.5vl:3b) ..."

        Sync-FormOcrOllamaModelsToAppData -SourceRoot $src -DestRoot $dst

        return

    }

    if (Test-ModelsReady $dst) {

        Write-Host "  Ollama models already present" -ForegroundColor DarkGray

        return

    }

    Write-Host "  Copying vision OCR models (qwen2.5vl:3b only, no text LLM) ..."

    Copy-FormOcrOllamaSeed -srcRoot $src -dstRoot $dst -Models (Get-FormOcrDefaultOllamaModels)

}



function New-Shortcut([string]$path, [string]$target, [string]$workDir, [string]$desc) {

    $wsh = New-Object -ComObject WScript.Shell

    $sc = $wsh.CreateShortcut($path)

    $sc.TargetPath = $target

    $sc.WorkingDirectory = $workDir

    $sc.Description = $desc

    $iconFile = Join-Path $workDir "FormOCR.ico"

    if (Test-Path $iconFile) {

        $sc.IconLocation = "$iconFile,0"

    }

    $sc.Save()

}



Write-Host "`n=== FormOCR Setup ===" -ForegroundColor Cyan

Write-Host "Install to: $InstallDir"

Write-Host "Data:     $dataRoot`n"



$exe = Join-Path $InstallDir "formocr-desktop.exe"

$seedOllama = Join-Path $InstallDir "seed\ollama"



if (-not $SeedOnly) {

    if (Test-Path $InstallDir) {

        Write-Host "Updating existing install ..."

        Remove-Item -Recurse -Force $InstallDir

    }

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

    Write-Host "Installing application (this may take a few minutes) ..."

    robocopy $SourceDir $InstallDir /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

    if ($LASTEXITCODE -ge 8) { throw "Failed to copy application (robocopy exit $LASTEXITCODE)" }

    $exe = Join-Path $InstallDir "formocr-desktop.exe"

    $seedOllama = Join-Path $InstallDir "seed\ollama"

    if (-not (Test-Path $seedOllama)) {

        $legacy = Join-Path $InstallDir "resources\seed\ollama"

        if (Test-Path $legacy) { $seedOllama = $legacy }

    }

} elseif (-not (Test-Path $exe)) {

    throw "SeedOnly: missing $exe"

}



Write-Host "`nPreparing offline models in AppData ..."

New-Item -ItemType Directory -Path $modelsRoot -Force | Out-Null

Copy-OllamaSeedIfNeeded $seedOllama $ollamaDst

if (Test-ModelsReady $ollamaDst) {

    Set-Content -Path $marker -Value "installed" -Encoding ascii

    Write-Host "  Models ready (qwen2.5vl:3b vision OCR)." -ForegroundColor Green

} else {

    Write-Host "  WARN: qwen2.5vl:3b not complete in AppData." -ForegroundColor Yellow

    Write-Host "  Rebuild installer: ollama pull qwen2.5vl:3b && npm run populate:assets:force && npm run build:installer" -ForegroundColor Yellow

}



$installReady = Join-Path $dataRoot ".install-ready-v1"

if (Test-Path $exe) {

    $warmed = Warm-FormOcrAtInstall -InstallDir $InstallDir -DataRoot $dataRoot

    if ($warmed) {

        Set-Content -Path $installReady -Value ("ready " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) -Encoding ascii

        Write-Host "  Setup complete - app will open immediately." -ForegroundColor Green

    }

} elseif (Test-Path $installReady) {

    Write-Host "  Engine already prepared." -ForegroundColor DarkGray

}



if (-not $SeedOnly) {

    $startMenu = [Environment]::GetFolderPath("Programs")

    $formDir = Join-Path $startMenu "FormOCR"

    New-Item -ItemType Directory -Path $formDir -Force | Out-Null

    New-Shortcut (Join-Path $formDir "FormOCR.lnk") $exe $InstallDir "FormOCR offline document OCR"

    $desktop = [Environment]::GetFolderPath("Desktop")

    New-Shortcut (Join-Path $desktop "FormOCR.lnk") $exe $InstallDir "FormOCR offline document OCR"

    Write-Host "`nShortcuts: Start Menu\FormOCR, Desktop\FormOCR.lnk"

}



Write-Host "`n=== Install complete ===" -ForegroundColor Green

Write-Host "Run FormOCR from the desktop shortcut or: $exe"



if ($LaunchAfter) {

    Start-Process $exe

}

