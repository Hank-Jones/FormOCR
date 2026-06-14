# Stop FormOCR-managed sidecars (Ollama on 11435, api-server).
param(
    [int]$ApiPort = 8765,
    [int]$OllamaPort = 11435
)

$ErrorActionPreference = "SilentlyContinue"
. "$PSScriptRoot\lib-formocr.ps1"

Write-Host "Stopping FormOCR sidecars..."

Get-Process -Name "formocr-desktop" -ErrorAction SilentlyContinue | Out-Null

if (Stop-FormOcrOllamaOnPort -Port $OllamaPort) {
    Write-Host "  Stopped Ollama on port $OllamaPort"
} else {
    Write-Host "  No Ollama listener on port $OllamaPort"
}

& "$PSScriptRoot\stop-formocr-api.ps1" -Port $ApiPort

Write-Host "Done."
