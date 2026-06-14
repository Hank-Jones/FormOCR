$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = "$Root\apps\api"
$OutDir = "$Root\apps\desktop\src-tauri\binaries\api-server"

Write-Host "Building API with PyInstaller..."
Set-Location $ApiDir
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    python -m venv .venv
}
$Py = ".\.venv\Scripts\python.exe"
$Pi = ".\.venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $Pi)) {
    & $Py -m pip install -q pyinstaller
}
& $Pi build.spec --noconfirm --distpath dist --workpath build

if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
Copy-Item -Recurse "$ApiDir\dist\api-server\*" $OutDir
$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss UTC")
Set-Content -Path "$OutDir\FORMOCR_API_BUILD.txt" -Value $stamp -Encoding ascii
Write-Host "API built to $OutDir (stamp $stamp)"

. (Join-Path $PSScriptRoot "lib-formocr.ps1")
Sync-FormOcrApiToAssets -Root $Root
