# Shared helpers for FormOCR scripts (local paths, no network).

# robocopy uses 0-7 for success; PowerShell otherwise exits with that code.
function Clear-RobocopyExitCode {
    if ($LASTEXITCODE -lt 8) {
        $global:LASTEXITCODE = 0
    }
}

function Test-FormOcrDirHasFiles([string]$path) {
    if (-not (Test-Path $path)) { return $false }
    $files = Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne '.gitkeep' }
    return $files.Count -gt 0
}

function Get-FormOcrOllamaExe {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path $cmd.Source)) { return $cmd.Source }
    foreach ($c in @(
            "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
            "$env:ProgramFiles\Ollama\ollama.exe"
        )) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Test-FormOcrOllamaGpuReady {
    param([Parameter(Mandatory)][string]$ExePath)
    if (-not (Test-Path $ExePath)) { return $false }
    $dir = Split-Path $ExePath -Parent
    return Test-Path (Join-Path $dir "lib\ollama")
}

function Resolve-FormOcrOllamaExe {
    param([string[]]$ExtraCandidates = @())
    $best = $null
    foreach ($c in @(
            "$env:LOCALAPPDATA\Programs\FormOCR\binaries\ollama.exe"
        ) + $ExtraCandidates + @(
            "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
            "$env:ProgramFiles\Ollama\ollama.exe"
        )) {
        if (-not (Test-Path $c)) { continue }
        if (Test-FormOcrOllamaGpuReady $c) { return $c }
        if (-not $best) { $best = $c }
    }
    if ($best) { return $best }
    return Get-FormOcrOllamaExe
}

function Stop-FormOcrOllamaOnPort {
    param([int]$Port = 11435)
    $killed = $false
    for ($i = 0; $i -lt 5; $i++) {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $conns) { break }
        foreach ($c in $conns) {
            taskkill /F /T /PID $c.OwningProcess 2>$null | Out-Null
            $killed = $true
        }
        Start-Sleep -Milliseconds 350
    }
    return $killed
}

function Copy-FormOcrOllamaBundle {
    param(
        [Parameter(Mandatory)][string]$SourceExe,
        [Parameter(Mandatory)][string]$DestDir
    )
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    Copy-Item $SourceExe (Join-Path $DestDir "ollama.exe") -Force
    $srcDir = Split-Path $SourceExe -Parent
    $libSrc = Join-Path $srcDir "lib"
    if (Test-Path $libSrc) {
        $libDst = Join-Path $DestDir "lib"
        if (Test-Path $libDst) { Remove-Item -Recurse -Force $libDst }
        Copy-Item $libSrc $libDst -Recurse -Force
        Write-Host "  Copied Ollama lib/ (GPU runners) -> $libDst"
    } else {
        Write-Warning "Source Ollama has no lib/ folder - GPU may not work offline: $SourceExe"
    }
}

function Get-FormOcrOllamaManifestRelPath {
    param([Parameter(Mandatory)][string]$Model)
    $m = $Model.Trim()
    $parts = $m.Split(':', 2)
    $name = $parts[0]
    $tag = if ($parts.Count -gt 1 -and $parts[1]) { $parts[1] } else { "latest" }
    return "manifests\registry.ollama.ai\library\$name\$tag"
}

function Test-FormOcrOllamaModelPresent {
    param(
        [string]$ModelsDir = "$env:USERPROFILE\.ollama\models",
        [Parameter(Mandatory)][string]$Model
    )
    if (-not (Test-FormOcrDirHasFiles $ModelsDir)) { return $false }
    $rel = Get-FormOcrOllamaManifestRelPath -Model $Model
    return Test-Path (Join-Path $ModelsDir $rel)
}

function Copy-FormOcrOllamaModelSeed {
    param(
        [Parameter(Mandatory)][string]$srcRoot,
        [Parameter(Mandatory)][string]$dstRoot,
        [Parameter(Mandatory)][string]$Model
    )
    $rel = Get-FormOcrOllamaManifestRelPath -Model $Model
    $manifestSrc = Join-Path $srcRoot $rel
    if (-not (Test-Path $manifestSrc)) {
        throw "Ollama manifest not found for $Model at $manifestSrc"
    }

    $dstManifest = Join-Path $dstRoot $rel
    New-Item -ItemType Directory -Path (Split-Path $dstManifest) -Force | Out-Null
    Copy-Item $manifestSrc $dstManifest -Force

    $manifest = Get-Content $dstManifest -Raw | ConvertFrom-Json
    $digests = @($manifest.config.digest)
    foreach ($layer in $manifest.layers) { $digests += $layer.digest }

    $blobsDst = Join-Path $dstRoot "blobs"
    New-Item -ItemType Directory -Path $blobsDst -Force | Out-Null
    foreach ($digest in $digests) {
        $hash = ($digest -replace '^sha256:', '').Trim()
        $blobName = "sha256-$hash"
        $srcBlob = Join-Path (Join-Path $srcRoot "blobs") $blobName
        if (-not (Test-Path $srcBlob)) {
            throw "Missing blob for ${Model}: $blobName"
        }
        Copy-Item $srcBlob (Join-Path $blobsDst $blobName) -Force
    }
}

function Copy-FormOcrOllamaSeed {
    param(
        [Parameter(Mandatory)][string]$srcRoot,
        [Parameter(Mandatory)][string]$dstRoot,
        [Parameter(Mandatory)][string[]]$Models
    )
    if (Test-Path $dstRoot) { Remove-Item -Recurse -Force $dstRoot }
    New-Item -ItemType Directory -Path $dstRoot -Force | Out-Null
    foreach ($m in $Models) {
        Copy-FormOcrOllamaModelSeed -srcRoot $srcRoot -dstRoot $dstRoot -Model $m
    }
    $mb = [math]::Round((Get-ChildItem $dstRoot -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
    $list = ($Models -join ", ")
    Write-Host ("  -> {0} (Ollama models: {1}, {2} MB)" -f $dstRoot, $list, $mb)
}

function Get-FormOcrDefaultOllamaModels {
  @("qwen2.5vl:3b")
}

# Vision OCR only — text LLMs (phi3, llama, etc.) are not bundled in FormOCR-Offline.
function Get-FormOcrOllamaModelBaseNames {
  param([string[]]$Models = (Get-FormOcrDefaultOllamaModels))
  $Models | ForEach-Object { ($_ -split ":", 2)[0].Trim().ToLower() } | Select-Object -Unique
}

function Assert-FormOcrOllamaSeedVisionOnly {
    param(
        [Parameter(Mandatory)][string]$ModelsDir,
        [string[]]$AllowedModels = (Get-FormOcrDefaultOllamaModels)
    )
    $lib = Join-Path $ModelsDir "manifests\registry.ollama.ai\library"
    if (-not (Test-Path $lib)) { return }
    $allowedBases = Get-FormOcrOllamaModelBaseNames -Models $AllowedModels
    foreach ($dir in Get-ChildItem $lib -Directory -ErrorAction SilentlyContinue) {
        $base = $dir.Name.ToLower()
        if ($allowedBases -notcontains $base) {
            throw @"
Offline bundle includes text LLM model '$($dir.Name)' under $ModelsDir.
FormOCR-Offline ships vision OCR only (qwen2.5vl:3b). Remove extra models and rebuild:
  npm run populate:assets:force
"@
        }
    }
    foreach ($m in $AllowedModels) {
        if (-not (Test-FormOcrOllamaModelPresent $ModelsDir $m)) {
            throw "Missing required vision model $m under $ModelsDir"
        }
    }
}

function Get-FormOcrOllamaManifestDigests {
    param([Parameter(Mandatory)][string]$ModelsDir)
    $digests = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $lib = Join-Path $ModelsDir "manifests\registry.ollama.ai\library"
    if (-not (Test-Path $lib)) { return $digests }
    foreach ($manifestFile in Get-ChildItem $lib -Recurse -File -ErrorAction SilentlyContinue) {
        try {
            $manifest = Get-Content $manifestFile.FullName -Raw | ConvertFrom-Json
            [void]$digests.Add([string]$manifest.config.digest)
            foreach ($layer in $manifest.layers) {
                [void]$digests.Add([string]$layer.digest)
            }
        } catch {
            Write-Host "  WARN: skipped invalid manifest $($manifestFile.FullName)" -ForegroundColor Yellow
        }
    }
    return $digests
}

function Remove-FormOcrOllamaExtraModels {
    param(
        [Parameter(Mandatory)][string]$ModelsDir,
        [string[]]$AllowedModels = (Get-FormOcrDefaultOllamaModels)
    )
    $allowedBases = Get-FormOcrOllamaModelBaseNames -Models $AllowedModels
    $lib = Join-Path $ModelsDir "manifests\registry.ollama.ai\library"
    $removed = @()
    if (Test-Path $lib) {
        foreach ($dir in Get-ChildItem $lib -Directory -ErrorAction SilentlyContinue) {
            if ($allowedBases -notcontains $dir.Name.ToLower()) {
                Remove-Item -Recurse -Force $dir.FullName
                $removed += $dir.Name
            }
        }
    }
    $keep = Get-FormOcrOllamaManifestDigests -ModelsDir $ModelsDir
    $blobs = Join-Path $ModelsDir "blobs"
    $pruned = 0
    if (Test-Path $blobs) {
        foreach ($blob in Get-ChildItem $blobs -File -Filter "sha256-*" -ErrorAction SilentlyContinue) {
            $digest = "sha256:" + ($blob.Name -replace '^sha256-', '')
            if (-not $keep.Contains($digest)) {
                Remove-Item $blob.FullName -Force
                $pruned++
            }
        }
    }
    return @{ removed_models = $removed; pruned_blobs = $pruned }
}

function Repair-FormOcrOllamaVisionSeed {
    param(
        [Parameter(Mandatory)][string]$ModelsDir,
        [Parameter(Mandatory)][string]$SrcRoot,
        [string[]]$AllowedModels = (Get-FormOcrDefaultOllamaModels)
    )
    New-Item -ItemType Directory -Path $ModelsDir -Force | Out-Null
    $repair = Remove-FormOcrOllamaExtraModels -ModelsDir $ModelsDir -AllowedModels $AllowedModels
    if ($repair.removed_models.Count -gt 0) {
        Write-Host "  Removed extra Ollama models: $($repair.removed_models -join ', ')"
    }
    if ($repair.pruned_blobs -gt 0) {
        Write-Host "  Pruned $($repair.pruned_blobs) unused blob(s)"
    }
    foreach ($m in $AllowedModels) {
        if (-not (Test-FormOcrOllamaModelPresent $ModelsDir $m)) {
            if (-not (Test-FormOcrOllamaModelPresent $SrcRoot $m)) {
                throw "Ollama model not found: $m. Run: ollama pull $m"
            }
            Write-Host "  Adding missing model $m ..."
            Copy-FormOcrOllamaModelSeed -srcRoot $SrcRoot -dstRoot $ModelsDir -Model $m
        }
    }
    Assert-FormOcrOllamaSeedVisionOnly -ModelsDir $ModelsDir -AllowedModels $AllowedModels
}

function Test-FormOcrOllamaNeedsRefresh {
    param(
        [Parameter(Mandatory)][string]$SrcRoot,
        [Parameter(Mandatory)][string]$DstRoot
    )
    if (-not (Test-Path $SrcRoot)) { return $false }
    if (-not (Test-FormOcrDirHasFiles $DstRoot)) { return $true }
    foreach ($m in (Get-FormOcrDefaultOllamaModels)) {
        if ((Test-FormOcrOllamaModelPresent $SrcRoot $m) -and -not (Test-FormOcrOllamaModelPresent $DstRoot $m)) {
            return $true
        }
    }
    return $false
}

function Sync-FormOcrOllamaModelsToAppData {
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [string]$DestRoot = "$env:LOCALAPPDATA\FormOCR\models\ollama",
        [string[]]$Models = (Get-FormOcrDefaultOllamaModels)
    )
    if (-not (Test-Path $SourceRoot)) {
        throw "Ollama seed not found: $SourceRoot"
    }
    New-Item -ItemType Directory -Path $DestRoot -Force | Out-Null
    $copied = @()
    foreach ($m in $Models) {
        if (Test-FormOcrOllamaModelPresent $DestRoot $m) {
            Write-Host "  $m already in AppData" -ForegroundColor DarkGray
            continue
        }
        if (-not (Test-FormOcrOllamaModelPresent $SourceRoot $m)) {
            Write-Host "  WARN: $m not in seed ($SourceRoot)" -ForegroundColor Yellow
            continue
        }
        Write-Host "  Copying $m ..."
        Copy-FormOcrOllamaModelSeed -srcRoot $SourceRoot -dstRoot $DestRoot -Model $m
        $copied += $m
    }
    if ($copied.Count -eq 0) {
        Write-Host "  No Ollama models copied (already complete)." -ForegroundColor DarkGray
    } else {
        $mb = [math]::Round((Get-ChildItem $DestRoot -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
        Write-Host "  Added: $($copied -join ', ') ($mb MB total in AppData)" -ForegroundColor Green
    }
}

# PP-OCRv4 paths required for offline ch + en (must match apps/api/app/services/ocr.py).
function Get-FormOcrPaddleRequiredRelPaths {
    $models = @(
        @{ det = "whl\det\ch\ch_PP-OCRv4_det_infer"; rec = "whl\rec\ch\ch_PP-OCRv4_rec_infer" },
        @{ det = "whl\det\en\en_PP-OCRv3_det_infer"; rec = "whl\rec\en\en_PP-OCRv4_rec_infer" }
    )
    $paths = @(
        "whl\cls\ch_ppocr_mobile_v2.0_cls_infer\inference.pdmodel",
        "whl\cls\ch_ppocr_mobile_v2.0_cls_infer\inference.pdiparams"
    )
    foreach ($m in $models) {
        foreach ($dir in @($m.det, $m.rec)) {
            $paths += "$dir\inference.pdmodel", "$dir\inference.pdiparams"
        }
    }
    return $paths
}

function Test-FormOcrPaddleModelsOffline {
    param([string]$PaddleRoot)
    if (-not $PaddleRoot -or -not (Test-Path $PaddleRoot)) { return $false }
    foreach ($rel in (Get-FormOcrPaddleRequiredRelPaths)) {
        if (-not (Test-Path (Join-Path $PaddleRoot $rel))) { return $false }
    }
    return $true
}

function Test-FormOcrPaddleModelsCh {
    param([string]$PaddleRoot)
    return Test-FormOcrPaddleModelsOffline $PaddleRoot
}

function Assert-FormOcrPaddleModelsOffline {
    param(
        [string]$PaddleRoot,
        [string]$Context = "PaddleOCR models"
    )
    if (Test-FormOcrPaddleModelsOffline $PaddleRoot) { return }
    $missing = @()
    foreach ($rel in (Get-FormOcrPaddleRequiredRelPaths)) {
        if (-not (Test-Path (Join-Path $PaddleRoot $rel))) { $missing += $rel }
    }
    $sample = ($missing | Select-Object -First 6) -join "`n  "
    $more = if ($missing.Count -gt 6) { "`n  ... and $($missing.Count - 6) more" } else { "" }
    throw @"
Incomplete $Context for offline OCR (Chinese, English / PP-OCRv4).

Root: $PaddleRoot
Missing (sample):
  $sample$more

On a connected PC, from the FormOCR repo:
  npm run setup
  npm run populate:assets:force
  npm run build:installer

Then copy dist\FormOCR-Offline to the offline PC and run FormOCR-Setup.cmd.
"@
}

function Assert-FormOcrPaddleModelsCh {
    param(
        [string]$PaddleRoot,
        [string]$Context = "PaddleOCR models"
    )
    Assert-FormOcrPaddleModelsOffline -PaddleRoot $PaddleRoot -Context $Context
}

function Resolve-FormOcrPaddleSrc {
    $primary = "$env:LOCALAPPDATA\FormOCR\models\paddle"
    if (Test-FormOcrPaddleModelsOffline $primary) { return $primary }
    $legacy = "$env:USERPROFILE\.paddleocr"
    if (Test-FormOcrPaddleModelsOffline $legacy) { return $legacy }
    return $null
}

# ZIP >2 GB: Compress-Archive fails. Prefer Windows tar, then 7-Zip, then .tar.gz.
function New-FormOcrPortableArchive {
    param(
        [Parameter(Mandatory)]
        [string]$SourceDir,
        [Parameter(Mandatory)]
        [string]$ZipPath
    )
    if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }

    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($tar) {
        Write-Host "Creating ZIP via tar (supports archives >2 GB)..."
        & $tar.Source -a -cf $ZipPath -C $SourceDir .
        if ($LASTEXITCODE -eq 0 -and (Test-Path $ZipPath)) {
            return @{ Path = $ZipPath; Format = 'zip' }
        }
        if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue }
        Write-Host "tar ZIP failed (exit $LASTEXITCODE), trying fallbacks..." -ForegroundColor Yellow
    }

    foreach ($7z in @(
            "${env:ProgramFiles}\7-Zip\7z.exe",
            "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
        )) {
        if (-not (Test-Path $7z)) { continue }
        Write-Host "Creating ZIP via 7-Zip..."
        & $7z a -tzip -mx=5 $ZipPath "$SourceDir\*"
        if ($LASTEXITCODE -eq 0 -and (Test-Path $ZipPath)) {
            return @{ Path = $ZipPath; Format = 'zip' }
        }
        if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue }
        break
    }

    if ($tar) {
        $tgzPath = [System.IO.Path]::ChangeExtension($ZipPath, '.tar.gz')
        if (Test-Path $tgzPath) { Remove-Item -Force $tgzPath }
        Write-Host "Creating .tar.gz via tar..."
        & $tar.Source -czf $tgzPath -C $SourceDir .
        if ($LASTEXITCODE -eq 0 -and (Test-Path $tgzPath)) {
            return @{ Path = $tgzPath; Format = 'tar.gz' }
        }
    }

    return $null
}

function Copy-FormOcrTree([string]$src, [string]$dst, [string]$label) {
    if (-not (Test-Path $src)) { throw "Missing $label source: $src" }
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    Write-Host "Copying $label ..."
    Copy-Item -Path "$src\*" -Destination $dst -Recurse -Force
    $mb = [math]::Round((Get-ChildItem $dst -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Host ("  -> {0} ({1} MB)" -f $dst, $mb)
}

function Test-FormOcrApiBundle {
    param(
        [Parameter(Mandatory)]
        [string]$ApiRoot
    )
    $checks = @(
        (Join-Path $ApiRoot "_internal\Cython\Utility\CppSupport.cpp"),
        (Join-Path $ApiRoot "_internal\paddleocr\tools\__init__.py"),
        (Join-Path $ApiRoot "api-server.exe")
    )
    foreach ($f in $checks) {
        if (-not (Test-Path $f)) {
            return $false
        }
    }
    return $true
}

function Assert-FormOcrApiBundle {
    param(
        [Parameter(Mandatory)]
        [string]$ApiRoot
    )
    if (Test-FormOcrApiBundle $ApiRoot) { return }
    throw @"
Incomplete api-server bundle at:
  $ApiRoot

Rebuild the offline package on a dev machine, then reinstall:
  cd <FormOCR repo>
  npm run build:installer

Or refresh API only (faster):
  npm run build:installer -- -SkipTauriBuild

Do not run FormOCR-Setup.cmd from an old dist\FormOCR-Offline folder.
"@
}

function Get-FormOcrApiSourceStamp {
    param([Parameter(Mandatory)][string]$ApiRoot)
    $stampFile = Join-Path $ApiRoot "FORMOCR_API_BUILD.txt"
    if (Test-Path $stampFile) {
        try {
            return [datetime]::ParseExact(
                (Get-Content $stampFile -Raw).Trim(),
                "yyyy-MM-dd HH:mm:ss UTC",
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::AssumeUniversal
            )
        } catch { }
    }
    $exe = Join-Path $ApiRoot "api-server.exe"
    if (Test-Path $exe) { return (Get-Item $exe).LastWriteTimeUtc }
    return [datetime]::MinValue
}

function Get-FormOcrApiSource {
    param(
        [Parameter(Mandatory)]
        [string]$Root
    )
    $candidates = @(
        (Join-Path $Root "apps\desktop\src-tauri\binaries\api-server"),
        (Join-Path $Root "assets\api-server")
    )
    $best = $null
    $bestStamp = [datetime]::MinValue
    foreach ($path in $candidates) {
        if (-not (Test-FormOcrApiBundle $path)) { continue }
        $stamp = Get-FormOcrApiSourceStamp $path
        if ($stamp -gt $bestStamp) {
            $best = $path
            $bestStamp = $stamp
        }
    }
    if (-not $best) {
        throw "No valid api-server bundle. Run: .\scripts\build-api.ps1"
    }
    return $best
}

function Sync-FormOcrApiToAssets {
    param(
        [Parameter(Mandatory)]
        [string]$Root
    )
    $TauriDir = Join-Path $Root "apps\desktop\src-tauri"
    $apiBuilt = Join-Path $TauriDir "binaries\api-server"
    $assetsApi = Join-Path $Root "assets\api-server"
    if (-not (Test-Path (Join-Path $apiBuilt "api-server.exe"))) {
        throw "Missing $apiBuilt\api-server.exe - run build-api.ps1 first."
    }
    if (Test-Path $assetsApi) { Remove-FormOcrPathForce $assetsApi | Out-Null }
    New-Item -ItemType Directory -Path $assetsApi -Force | Out-Null
    robocopy $apiBuilt $assetsApi /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed syncing api-server to assets (exit $LASTEXITCODE)" }
    Clear-RobocopyExitCode
    Assert-FormOcrApiBundle -ApiRoot $assetsApi
    Write-Host "  api-server synced to assets/api-server" -ForegroundColor Green
}

function Copy-FormOcrApiBundle {
    param(
        [Parameter(Mandatory)]
        [string]$SourceApi,
        [Parameter(Mandatory)]
        [string]$DestApi
    )
    Assert-FormOcrApiBundle -ApiRoot $SourceApi
    if (Test-Path $DestApi) { Remove-FormOcrPathForce $DestApi | Out-Null }
    New-Item -ItemType Directory -Path $DestApi -Force | Out-Null
    robocopy $SourceApi $DestApi /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed for api-server (exit $LASTEXITCODE)" }
    Clear-RobocopyExitCode
    Assert-FormOcrApiBundle -ApiRoot $DestApi
}

function Sync-FormOcrPaddleFromInstallSeed {
    param(
        [Parameter(Mandatory)]
        [string]$InstallDir,
        [Parameter(Mandatory)]
        [string]$PaddleDst
    )
    if (Test-FormOcrPaddleModelsOffline $PaddleDst) { return }

    foreach ($rel in @("seed\paddle", "resources\seed\paddle")) {
        $src = Join-Path $InstallDir $rel
        if (-not (Test-FormOcrPaddleModelsOffline $src)) { continue }
        Write-Host "  Copying PaddleOCR models from installer seed ..."
        if (Test-Path $PaddleDst) { Remove-Item -Recurse -Force $PaddleDst }
        New-Item -ItemType Directory -Path (Split-Path $PaddleDst -Parent) -Force | Out-Null
        robocopy $src $PaddleDst /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy failed seeding paddle (exit $LASTEXITCODE)" }
        Clear-RobocopyExitCode
        Assert-FormOcrPaddleModelsOffline $PaddleDst "installer seed -> AppData"
        return
    }
}

function Stop-FormOcrLockingProcesses {
    foreach ($name in @('formocr-desktop', 'api-server', 'ollama')) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 600
}

# Run during FormOCR-Setup: verify bundled api-server, init DB, warm OCR. App launch stays instant.
function Warm-FormOcrAtInstall {
    param(
        [Parameter(Mandatory)]
        [string]$InstallDir,
        [Parameter(Mandatory)]
        [string]$DataRoot,
        [int]$Port = 8765,
        [int]$OcrWarmMinutes = 12
    )

    $apiRoot = Join-Path $InstallDir "binaries\api-server"
    $apiExe = Join-Path $apiRoot "api-server.exe"
    if (-not (Test-Path $apiExe)) {
        Write-Host "  Skip engine warm-up (api-server.exe not found)" -ForegroundColor DarkYellow
        return $false
    }
    Assert-FormOcrApiBundle -ApiRoot $apiRoot

    New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
    Set-Content -Path (Join-Path $DataRoot "api.port") -Value $Port -Encoding ascii -NoNewline

    Stop-FormOcrLockingProcesses

    Write-Host "`nPreparing FormOCR engine (database + Qwen vision warm-up) ..."
    Write-Host "  This runs once during setup and can take several minutes."

    $env:FORMOCR_DATA_DIR = $DataRoot
    $env:FORMOCR_PORT = "$Port"
    $env:FORMOCR_OCR_ENGINE = "qwen"
    $env:FORMOCR_HANDWRITING_OCR_ENABLED = "true"
    $env:FORMOCR_HANDWRITING_OCR_MODEL = "qwen2.5vl:3b"
    $env:FORMOCR_AI_CORRECTION_ENABLED = "true"
    $proc = Start-Process -FilePath $apiExe -WorkingDirectory (Split-Path $apiExe) -PassThru -WindowStyle Hidden
    $liveOk = $false
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) {
            throw "api-server.exe exited during setup (code $($proc.ExitCode)). Check antivirus or reinstall."
        }
        foreach ($path in @("/health/live", "/health")) {
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:${Port}${path}" -UseBasicParsing -TimeoutSec 4
                if ($r.StatusCode -eq 200) {
                    $liveOk = $true
                    break
                }
            } catch {
                # keep polling
            }
        }
        if ($liveOk) { break }
        Start-Sleep -Seconds 2
    }
    if (-not $liveOk) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        throw "FormOCR engine did not start during setup. Check antivirus or run setup as administrator."
    }
    Write-Host "  Engine online." -ForegroundColor Green

    Write-Host "  Verifying OCR engine (up to 3 minutes) ..." -ForegroundColor DarkGray
    $ocrDeadline = (Get-Date).AddMinutes(3)
    $ocrReady = $false
    $warmStart = Get-Date
    $poll = 0
    while ((Get-Date) -lt $ocrDeadline) {
        if ($proc.HasExited) { break }
        try {
            $h = Invoke-RestMethod -Uri "http://127.0.0.1:${Port}/health" -TimeoutSec 120
            if ($h.ocr_error) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $err = "$($h.ocr_error)"
                if ($err -match 'CppSupport\.cpp|Cython\\Utility') {
                    throw @"
OCR failed: bundled api-server is outdated or incomplete.
  $err

Rebuild on the dev PC: npm run build:installer
Then run FormOCR-Setup.cmd from the NEW dist\FormOCR-Offline folder (not an old copy).
"@
                }
                if ($err -match 'Download from .* failed|Retry limit reached') {
                    throw @"
OCR failed: tried to download models (no network on offline PC).
  $err

Fix:
  1. On a connected PC: ollama pull qwen2.5vl:3b && npm run populate:assets:force && npm run build:installer
  2. Copy the NEW dist\FormOCR-Offline folder to this PC
  3. Delete: $(Join-Path $DataRoot 'models\ollama')
  4. Run FormOCR-Setup.cmd again

Check installer has app\seed\ollama with qwen2.5vl:3b manifests and blobs.
"@
                }
                throw "OCR failed: $err"
            }
            if ($h.ocr_ready) {
                $ocrReady = $true
                break
            }
        } catch {
            if ($_.Exception.Message -match '^OCR failed:') { throw }
            # still warming
        }
        $poll++
        $elapsedSec = [int]((Get-Date) - $warmStart).TotalSeconds
        $pct = [Math]::Min(99, [int]($elapsedSec / ($OcrWarmMinutes * 60) * 100))
        Write-Progress -Activity "FormOCR setup" `
            -Status "Loading OCR models ($elapsedSec s elapsed) ..." `
            -PercentComplete $pct
        Start-Sleep -Seconds 5
    }
    Write-Progress -Activity "FormOCR setup" -Completed
    if ($ocrReady) {
        $elapsed = [int]((Get-Date) - $warmStart).TotalSeconds
        Write-Host "  OCR ready (${elapsed}s)." -ForegroundColor Green
    } else {
        Write-Host "  OCR warm-up did not finish in time; the app will finish loading on first use." -ForegroundColor DarkYellow
    }

    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Stop-FormOcrLockingProcesses
    return $true
}

function Remove-FormOcrPathForce([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return $true }
    for ($i = 1; $i -le 4; $i++) {
        try {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
            return $true
        } catch {
            if ($i -lt 4) {
                Write-Host "  Retry removing locked path ($i/3)..." -ForegroundColor DarkYellow
                Stop-FormOcrLockingProcesses
                Start-Sleep -Seconds 1
            }
        }
    }
    return $false
}

# Build into staging, then swap into DistRoot. If dist\FormOCR-Offline is locked, publishes FormOCR-Offline.new.
function Publish-FormOcrOfflineDistRoot {
    param(
        [Parameter(Mandatory)]
        [string]$StagingRoot,
        [Parameter(Mandatory)]
        [string]$DistRoot
    )
    $parent = Split-Path -Parent $DistRoot
    $leaf = Split-Path -Leaf $DistRoot
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    if (-not (Test-Path -LiteralPath $StagingRoot)) {
        throw "Staging folder missing: $StagingRoot"
    }

    Stop-FormOcrLockingProcesses

    if (Test-Path -LiteralPath $DistRoot) {
        if (-not (Remove-FormOcrPathForce $DistRoot)) {
            $archiveName = "${leaf}.old.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
            try {
                Write-Host "dist\$leaf is locked; renaming to $archiveName" -ForegroundColor Yellow
                Rename-Item -LiteralPath $DistRoot -NewName $archiveName -Force -ErrorAction Stop
            } catch {
                $altLeaf = "${leaf}.new"
                $altPath = Join-Path $parent $altLeaf
                if (Test-Path -LiteralPath $altPath) {
                    Remove-FormOcrPathForce $altPath | Out-Null
                }
                Rename-Item -LiteralPath $StagingRoot -NewName $altLeaf -Force
                Write-Host ""
                Write-Host "Could not replace locked folder: $DistRoot" -ForegroundColor Yellow
                Write-Host "New package is ready at:" -ForegroundColor Green
                Write-Host "  $altPath"
                Write-Host ""
                Write-Host "Close FormOCR, close Explorer on dist\, then either:" -ForegroundColor Yellow
                Write-Host "  - Delete or rename the old $leaf folder, and rename $altLeaf to $leaf"
                Write-Host "  - Or copy $altPath to another PC and run FormOCR-Setup.cmd there"
                Write-Host ""
                return $altPath
            }
        }
    }

    Rename-Item -LiteralPath $StagingRoot -NewName $leaf -Force
    Write-Host "Published: $DistRoot" -ForegroundColor Green

    Get-ChildItem $parent -Directory -Filter "${leaf}.old.*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 2 |
        ForEach-Object {
            Write-Host "Removing old build: $($_.Name)" -ForegroundColor DarkGray
            Remove-FormOcrPathForce $_.FullName | Out-Null
        }

    return $DistRoot
}
