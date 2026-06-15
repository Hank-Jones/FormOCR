$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

$ApiDir = "$Root\apps\api"

$VenvCandidates = @(
    "$ApiDir\venv\Scripts\python.exe",
    "$ApiDir\venv-dev312\Scripts\python.exe"
)
$VenvPython = $VenvCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not (Test-Path $VenvPython)) {

    throw "Missing API venv. Run: cd apps\api && python -m venv venv && pip install -r requirements.txt"

}



$env:FORMOCR_DATA_DIR = "$env:LOCALAPPDATA\FormOCR"

$env:FORMOCR_PORT = "8765"

$env:FORMOCR_DEV_API = "http://127.0.0.1:8765"
$env:FORMOCR_OLLAMA_HOST = "http://127.0.0.1:11435"
$env:FORMOCR_OCR_ENGINE = "qwen"
$env:FORMOCR_HANDWRITING_OCR_ENABLED = "true"
$env:FORMOCR_HANDWRITING_OCR_MODEL = "qwen2.5vl:3b"
$env:FORMOCR_AI_CORRECTION_ENABLED = "true"

New-Item -ItemType Directory -Path $env:FORMOCR_DATA_DIR -Force | Out-Null



& "$Root\scripts\stop-formocr-api.ps1" -Port 8765



& "$Root\scripts\start-ollama.ps1" -Port 11435 2>$null



Write-Host "Starting FormOCR API (venv) on port 8765..."

$apiJob = Start-Job -ScriptBlock {

    param($Python, $ApiDir, $DataDir, $OllamaHost)

    Set-Location $ApiDir

    $env:FORMOCR_DATA_DIR = $DataDir
    $env:FORMOCR_PORT = "8765"
    $env:FORMOCR_OLLAMA_HOST = $OllamaHost
    $env:FORMOCR_OCR_ENGINE = "qwen"
    $env:FORMOCR_HANDWRITING_OCR_ENABLED = "true"
    $env:FORMOCR_HANDWRITING_OCR_MODEL = "qwen2.5vl:3b"
    $env:FORMOCR_AI_CORRECTION_ENABLED = "true"

    & $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8765

} -ArgumentList $VenvPython, $ApiDir, $env:FORMOCR_DATA_DIR, $env:FORMOCR_OLLAMA_HOST



Write-Host "Waiting for API health..."

$ok = $false

for ($i = 0; $i -lt 60; $i++) {

    try {

        $h = Invoke-RestMethod "http://127.0.0.1:8765/health" -TimeoutSec 2

        $schema = Invoke-RestMethod "http://127.0.0.1:8765/openapi.json" -TimeoutSec 2

        $types = $schema.components.schemas.FieldType.enum
        $formRoute = $schema.paths.PSObject.Properties | Where-Object { $_.Name -eq "/forms/{form_id}" }
        $formMethods = @()
        if ($formRoute) {
            $formMethods = @($formRoute.Value.PSObject.Properties.Name)
        }

        if ($types -notcontains "gender") {

            throw "API on 8765 is an OLD build (field types: $($types -join ', ')). Stop other Python/api-server on this port."

        }

        if ($formMethods -notcontains "delete") {

            throw "API on 8765 is an OLD build (missing DELETE /forms/{form_id}). Stop other Python/api-server on this port."

        }

        Write-Host "API: $($h.status) | OCR: $($h.ocr_ready) | Field types: $($types.Count) (incl. gender, location) | Form methods: $($formMethods -join ', ')"

        $ok = $true

        break

    } catch {

        if ($_.Exception.Message -match "OLD build") { throw }

        Start-Sleep -Seconds 2

    }

}

if (-not $ok) {

    Stop-Job $apiJob -ErrorAction SilentlyContinue

    Remove-Job $apiJob -Force -ErrorAction SilentlyContinue

    throw "API did not start on port 8765. Check: Receive-Job -Id $($apiJob.Id)"

}



Write-Host "Starting Tauri dev..."

Set-Location "$Root\apps\desktop"

try {

    npm run tauri dev

} finally {

    Stop-Job $apiJob -ErrorAction SilentlyContinue

    Remove-Job $apiJob -Force -ErrorAction SilentlyContinue

    . "$Root\scripts\lib-formocr.ps1"
    if (Stop-FormOcrOllamaOnPort -Port 11435) {
        Write-Host "Stopped dev Ollama on port 11435"
    }

}

