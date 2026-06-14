# FormOCR offline assets (copy this folder with the project)

Everything needed to run FormOCR **without downloading** on another PC lives here.

## Layout

```
assets/
  ollama/
    ollama.exe          # Windows Ollama binary
  models/
    ollama/             # Ollama models (manifests + blobs), e.g. qwen2.5vl:3b
  api-server/           # PyInstaller API bundle (api-server.exe + deps)
```

Approximate size: mostly `qwen2.5vl:3b` (~3–4 GB) plus API binary.

## One-time: fill assets on a connected PC

From repo root:

```powershell
npm run setup
npm run populate:assets
```

This copies from your machine into `assets/` (no network if `qwen2.5vl:3b` is already pulled).

### Vision model for handwriting OCR

```powershell
ollama pull qwen2.5vl:3b
npm run populate:assets:force
```

## On another (offline) PC

1. Copy the **entire** `FormOCR` project folder (including `assets/`).
2. Install Node, Rust, Python once if you need to rebuild; or use pre-built `dist\FormOCR-Offline\portable`.
3. Build / run:

```powershell
npm run prepare:installer    # assets -> src-tauri/resources
npm run build:installer      # creates dist\FormOCR-Offline\
```

Or run portable directly if already built:

```powershell
dist\FormOCR-Offline\portable\Run FormOCR.bat
```

## Refresh

```powershell
npm run populate:assets:force
```

## Note

Large files under `assets/` are gitignored. Use USB/cloud zip to move the project.
