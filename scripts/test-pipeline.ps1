# End-to-end offline pipeline test (preprocess + OCR + LLM)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:FORMOCR_DATA_DIR = "$env:LOCALAPPDATA\FormOCR"
$env:FORMOCR_OCR_ENGINE = "qwen"
$env:FORMOCR_HANDWRITING_OCR_ENABLED = "true"
$env:FORMOCR_HANDWRITING_OCR_MODEL = "qwen2.5vl:3b"

& "$Root\scripts\start-ollama.ps1"

$ApiDir = "$Root\apps\api"
Set-Location $ApiDir
. .\.venv\Scripts\Activate.ps1

Write-Host "`n=== Component test ===" -ForegroundColor Cyan
python -c @"
import asyncio
import cv2
import numpy as np
from app.config import settings
from app.services.preprocess import preprocess_page
from app.services.ocr import ensure_qwen_session_ready, ocr_crop, is_ocr_ready, uses_qwen_only
from app.services.ai_correct import check_ollama_model

settings.ensure_dirs()
img = np.ones((200, 600, 3), dtype=np.uint8) * 255
cv2.putText(img, 'J0hn Sm1th', (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
proc = preprocess_page(img)
if uses_qwen_only():
    ok, msg = ensure_qwen_session_ready()
    print(f'Qwen warm: ok={ok} {msg}')
else:
    from app.services.ocr import warm_ocr
    warm_ocr()
text, conf = ocr_crop(proc)
print(f'Preprocess+OCR: text={text!r} conf={conf:.2f} ocr_ready={is_ocr_ready()}')

async def vision():
    ok, model = await check_ollama_model(settings.handwriting_ocr_model)
    print(f'Ollama vision model {settings.handwriting_ocr_model}: present={model} host_ok={ok}')
asyncio.run(vision())
"@

Write-Host "`n=== API health ===" -ForegroundColor Cyan
try {
    $h = Invoke-RestMethod "http://127.0.0.1:8765/health" -TimeoutSec 3
    $h | ConvertTo-Json
} catch {
    Write-Host "Start API first: cd apps\api; python -m uvicorn app.main:app --port 8765"
}
