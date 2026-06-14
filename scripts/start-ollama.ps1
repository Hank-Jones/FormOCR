param(
    [int]$Port = 11434
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib-formocr.ps1"

$Root = Split-Path -Parent $PSScriptRoot
$bundled = Join-Path $Root "apps\desktop\src-tauri\binaries\ollama.exe"
$installed = Join-Path $env:LOCALAPPDATA "Programs\FormOCR\binaries\ollama.exe"

$ollama = Resolve-FormOcrOllamaExe -ExtraCandidates @($installed, $bundled)
if (-not $ollama -or -not (Test-Path $ollama)) {
    Write-Host "Ollama not installed. Run: .\scripts\setup-offline.ps1"
    exit 1
}
$ollamaDir = Split-Path $ollama -Parent
if (-not (Test-FormOcrOllamaGpuReady $ollama)) {
    Write-Warning "Ollama at $ollama has no lib\ollama - vision OCR will run on CPU/RAM."
}

$tagsUrl = "http://127.0.0.1:$Port/api/tags"
$modelsDir = Join-Path $env:LOCALAPPDATA "FormOCR\models\ollama"
New-Item -ItemType Directory -Path $modelsDir -Force | Out-Null

function Test-OllamaPort {
    param([int]$P)
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$P/api/tags" -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-OllamaOnGpu {
    param([int]$P)
    try {
        $ps = Invoke-RestMethod -Uri "http://127.0.0.1:$P/api/ps" -TimeoutSec 3
        foreach ($m in @($ps.models)) {
            if ($m.size_vram -gt 0) { return $true }
        }
        return $false
    } catch {
        return $false
    }
}

if (Test-OllamaPort $Port) {
    if (Test-FormOcrOllamaGpuReady $ollama) {
        Write-Host "Ollama already running on port $Port"
    } else {
        Write-Host "Restarting Ollama on port $Port (previous instance may lack GPU libs)..."
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
    }
}

if (-not (Test-OllamaPort $Port)) {
    Write-Host "Starting Ollama on port $Port ($ollama)..."
    $env:OLLAMA_HOST = "127.0.0.1:$Port"
    $env:OLLAMA_MODELS = $modelsDir
    $env:CUDA_VISIBLE_DEVICES = "0"
    $env:OLLAMA_FLASH_ATTENTION = "1"
    $env:OLLAMA_MAX_LOADED_MODELS = "1"
    $env:OLLAMA_NUM_PARALLEL = "1"
    if ($ollamaDir -notin ($env:PATH -split ';')) {
        $env:PATH = "$ollamaDir;$env:PATH"
    }
    Start-Process -FilePath $ollama -ArgumentList "serve" -WorkingDirectory $ollamaDir -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-OllamaPort $Port) { break }
        Start-Sleep -Seconds 1
    }

    if (-not (Test-OllamaPort $Port)) {
        throw "Ollama did not start on port $Port. Try running manually: `"$ollama`" serve"
    }
}

$tags = Invoke-RestMethod -Uri $tagsUrl -TimeoutSec 10
$hw = if ($env:FORMOCR_HANDWRITING_OCR_MODEL) { $env:FORMOCR_HANDWRITING_OCR_MODEL } else { "qwen2.5vl:3b" }
$hasHw = $tags.models | Where-Object { $_.name -eq $hw -or $_.name -like "$hw*" }
if (-not $hasHw) {
    Write-Host "Pulling vision OCR model $hw (one-time download)..."
    $env:OLLAMA_HOST = "127.0.0.1:$Port"
    & $ollama pull $hw
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Model pull failed. Run manually: ollama pull $hw"
        exit 1
    }
}

Write-Host "Ollama ready on port $Port ($ollama) - model: $hw"
