# FormOCR

Offline Windows desktop app for no-code form recognition: visual template learning, crop-based OCR, validation, and optional local AI correction.

## Stack

- **Desktop:** Tauri 2 + React + TypeScript + Vite
- **Backend:** Python FastAPI (sidecar)
- **OCR:** OpenCV preprocessing + Qwen2.5-VL (`qwen2.5vl:3b`) via bundled Ollama (offline installer)
- **Optional dev:** hybrid PaddleOCR + Qwen when `FORMOCR_OCR_ENGINE=hybrid`
- **DB:** SQLite (`%LOCALAPPDATA%/FormOCR`)

## Prerequisites
####
- Node.js 20+
- Rust (for Tauri)
- Python 3.11+

## One-time offline setup (downloads models)

Run from repo root (requires internet once; vision model ~3–4 GB):

```powershell
.\scripts\setup-offline.ps1
npm run populate:assets
```

This installs Python deps (for building the API bundle), installs Ollama, and pulls `qwen2.5vl:3b` for handwriting OCR. The offline installer does **not** bundle Paddle weights or `phi3:mini`.

## Development

From repo root:

```powershell
npm run dev          # Ollama + API + Tauri (recommended)
npm run tauri:dev    # Desktop only (start API separately)
npm run test:pipeline
```

Or:

```powershell
# All-in-one (starts Ollama, API, Tauri)
.\scripts\dev.ps1
```

Or manually:

```powershell
# Terminal 1
.\scripts\start-ollama.ps1
cd apps\api
.\.venv\Scripts\Activate.ps1
$env:FORMOCR_DATA_DIR = "$env:LOCALAPPDATA\FormOCR"
$env:FORMOCR_OCR_ENGINE = "qwen"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765

# Terminal 2
cd apps\desktop
$env:FORMOCR_DEV_API = "http://127.0.0.1:8765"
npm run tauri dev
```

Verify stack: `.\scripts\test-pipeline.ps1`

## Troubleshooting `npm run tauri dev`

**Stuck on “Waiting for frontend dev server on http://localhost:1420”**  
Vite must bind to `127.0.0.1` (not only `localhost`). This repo sets `devUrl` and Vite `host` accordingly.

**Rust build: `resource file icon.ico is not in 3.00 format`**  
Regenerate the icon:
```powershell
cd apps/api
.\.venv\Scripts\pip install pillow
.\.venv\Scripts\python -c "from PIL import Image; Image.new('RGB',(256,256),(59,130,246)).save(r'..\..\apps\desktop\src-tauri\icons\icon.ico', format='ICO')"
```

**Rust build: `binaries\api-server-...exe doesn't exist`**  
Sidecars are only required for production installers. Dev uses system Python/Ollama. Before `tauri build`, run `.\scripts\build-api.ps1` and `.\scripts\bundle-ollama.ps1`, then add `externalBin` back to `tauri.conf.json` if needed.

## Offline assets in the project (`assets/`)

All models and binaries can live **inside the repo** so you copy one folder to another PC:

```
assets/
  ollama/ollama.exe
  models/ollama/          # qwen2.5vl:3b only
  api-server/             # PyInstaller API
```

**Fill once** on a PC that already has models (no download if setup was done):

```powershell
npm run populate:assets
```

**On another PC** (copy whole `FormOCR` folder including `assets/`):

```powershell
npm run build:installer
```

See [assets/README.md](assets/README.md).

## Offline installer (`dist\FormOCR-Offline`)

```powershell
npm run build:installer
# Runs: build-api.ps1 -> prepare-installer-assets.ps1 -> Tauri release -> dist\FormOCR-Offline
# Faster if only UI changed: npm run build:installer -- -SkipApiBuild
# Skip Tauri rebuild: npm run build:installer -- -SkipTauriBuild
```

**Output:** `dist\FormOCR-Offline\`

| Item | Purpose |
|------|---------|
| `FormOCR_*_x64-setup.exe` | Standard Windows install |
| `portable\` | Copy-to-USB tree (`formocr-desktop.exe` + bundled resources) |
| `README-OFFLINE.txt` | Instructions for offline PCs |

First launch copies bundled models from the installer into `%LOCALAPPDATA%\FormOCR\models\` (one-time, a few minutes). No `ollama pull` or downloads on the target PC.

Rebuild bundled models only: `npm run prepare:installer -- -Force`  
First-time `assets/`: `npm run populate:assets` (then `build:installer`).

## Build (API only, dev)

```powershell
.\scripts\build-api.ps1
```

## Data directory

`%LOCALAPPDATA%\FormOCR\`
- `formocr.db` — SQLite
- `images/` — uploaded scans
- `models/` — OCR / LLM assets
- `logs/`
"# FormOCR" 
"# FormOCR" 
"# io" 
"# FormOCR" 
"# FormOCR" 
