# Dev helper: pull the vision OCR model into local Ollama cache (requires internet).
$ErrorActionPreference = "Stop"
$env:OLLAMA_HOST = "http://127.0.0.1:11434"
$hw = if ($env:FORMOCR_HANDWRITING_OCR_MODEL) { $env:FORMOCR_HANDWRITING_OCR_MODEL } else { "qwen2.5vl:3b" }
Write-Host "Pulling handwriting OCR model $hw ..."
ollama pull $hw
Write-Host "Done."
