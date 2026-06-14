# Stop whatever is listening on FormOCR API port (default 8765).
param([int]$Port = 8765)

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Host "No process listening on port $Port."
    exit 0
}
$pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $pids) {
    if ($procId -le 0) { continue }
    try {
        $proc = Get-Process -Id $procId -ErrorAction Stop
        Write-Host "Stopping $($proc.ProcessName) (PID $procId) on port $Port ..."
        Stop-Process -Id $procId -Force
    } catch {
        Write-Host "Could not stop PID $procId : $_"
    }
}
Write-Host "Port $Port is free."
