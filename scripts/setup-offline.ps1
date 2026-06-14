# FormOCR offline setup: Python deps, Ollama + qwen2.5vl:3b (no Paddle weights for offline bundle)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

$ApiDir = "$Root\apps\api"

$DataDir = "$env:LOCALAPPDATA\FormOCR"

$ModelsDir = "$DataDir\models"



Write-Host "=== FormOCR Offline Setup (qwen2.5vl:3b) ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Path $DataDir, $ModelsDir, "$DataDir\images", "$DataDir\logs" -Force | Out-Null



Write-Host "`n[1/3] Python dependencies..." -ForegroundColor Yellow

Set-Location $ApiDir

if (-not (Test-Path .\.venv\Scripts\python.exe)) {

    python -m venv .venv

}

$py = ".\.venv\Scripts\python.exe"

& $py -m pip install --upgrade pip -q

if ($LASTEXITCODE -ne 0) {

    Write-Host "  pip self-upgrade skipped (optional)" -ForegroundColor DarkGray

    $global:LASTEXITCODE = 0

}

& $py -m pip install -r requirements.txt -r requirements-ocr.txt

if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }

Write-Host "  Python env ready (Paddle libs for API build only; offline OCR uses Qwen vision)." -ForegroundColor Green



Write-Host "`n[2/3] Ollama..." -ForegroundColor Yellow

. "$PSScriptRoot\lib-formocr.ps1"

$ollamaExe = Get-FormOcrOllamaExe

if ($ollamaExe) {

    $env:Path = "$(Split-Path $ollamaExe);$env:Path"

    Write-Host "Found local Ollama: $ollamaExe"

} else {

    $ollamaInstaller = "$env:TEMP\OllamaSetup.exe"

    if (-not (Test-Path $ollamaInstaller)) {

        Write-Host "Downloading Ollama for Windows..."

        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $ollamaInstaller -UseBasicParsing

    }

    Write-Host "Installing Ollama (silent). Approve UAC if prompted..."

    Start-Process -FilePath $ollamaInstaller -ArgumentList "/SILENT" -Wait

    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    $ollamaExe = Get-FormOcrOllamaExe

}



if (-not $ollamaExe) {

    Write-Host "WARN: Ollama not found. Install manually from https://ollama.com/download" -ForegroundColor Red

} else {

    Write-Host "Ollama: $ollamaExe"

    try {

        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null

    } catch {

        Write-Host "Starting Ollama service..."

        Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden

        Start-Sleep -Seconds 5

    }



    $hwModel = if ($env:FORMOCR_HANDWRITING_OCR_MODEL) { $env:FORMOCR_HANDWRITING_OCR_MODEL } else { "qwen2.5vl:3b" }

    if (Test-FormOcrOllamaModelPresent -Model $hwModel) {

        Write-Host "`n[3/3] $hwModel already present (skip pull)" -ForegroundColor Green

    } else {

        Write-Host "`n[3/3] Pulling vision OCR model $hwModel (offline after this)..." -ForegroundColor Yellow

        & $ollamaExe pull $hwModel

    }

}



Write-Host "`nWriting config..." -ForegroundColor Yellow

$envFile = @"

FORMOCR_DATA_DIR=$DataDir

FORMOCR_PORT=8765

FORMOCR_OCR_ENGINE=qwen

FORMOCR_HANDWRITING_OCR_ENABLED=true

FORMOCR_HANDWRITING_OCR_MODEL=qwen2.5vl:3b

FORMOCR_AI_CORRECTION_ENABLED=false

OLLAMA_HOST=http://127.0.0.1:11434

"@

$envFile | Out-File -FilePath "$Root\.env.local" -Encoding utf8



Write-Host "`n=== Setup complete ===" -ForegroundColor Green

Write-Host "Data: $DataDir"

Write-Host "Populate installer assets: npm run populate:assets"

Write-Host "Start API:  cd apps\api; .\.venv\Scripts\Activate.ps1; python -m uvicorn app.main:app --host 127.0.0.1 --port 8765"

Write-Host "Start UI:   cd apps\desktop; npm run tauri dev"

