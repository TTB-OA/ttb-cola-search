param(
    [switch]$NoReload,
    [switch]$SkipPortCleanup
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Stop-ProcessOnPort {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $connections = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $connections) {
        return
    }

    $ownerProcessIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerProcessId in $ownerProcessIds) {
        if ($ownerProcessId -and $ownerProcessId -ne $PID) {
            try {
                Stop-Process -Id $ownerProcessId -Force -ErrorAction Stop
                Write-Host "Stopped process $ownerProcessId listening on port $Port"
            }
            catch {
                Write-Warning "Could not stop process $ownerProcessId on port ${Port}: $($_.Exception.Message)"
            }
        }
    }
}

if (-not $SkipPortCleanup) {
    Stop-ProcessOnPort -Port 8000
    Stop-ProcessOnPort -Port 5173
}

$apiCommand = if ($NoReload) { 'uv run python run.py' } else { 'uv run python run.py --reload' }

Start-Process powershell -ArgumentList @(
    '-NoExit',
    '-ExecutionPolicy', 'Bypass',
    '-Command', "Set-Location '$root'; $apiCommand"
)

Start-Process powershell -ArgumentList @(
    '-NoExit',
    '-ExecutionPolicy', 'Bypass',
    '-Command', "Set-Location '$root/frontend'; npm run dev"
)

Write-Host 'Started API and frontend in separate PowerShell windows.'
Write-Host 'API:      http://127.0.0.1:8000'
Write-Host 'Frontend: http://localhost:5173'
Write-Host "API reload is enabled by default. Use -NoReload to disable it."
Write-Host "Ports 8000 and 5173 are cleaned up by default. Use -SkipPortCleanup to keep existing processes."
