# Copy PaddleOCR models from user profile into FormOCR offline store
$src = "$env:USERPROFILE\.paddleocr"
$dst = "$env:LOCALAPPDATA\FormOCR\models\paddle"
if (Test-Path $src) {
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    Copy-Item -Path "$src\*" -Destination $dst -Recurse -Force
    Write-Host "Copied Paddle models to $dst"
} else {
    Write-Host "No models at $src - run Paddle warm-up first"
}
