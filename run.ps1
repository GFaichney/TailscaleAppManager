$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path .venv)) {
    throw 'Virtual environment missing. Run .\setup.ps1 first.'
}

$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Port = if ($env:WRAPPER_PORT) { $env:WRAPPER_PORT } else { '8080' }
$Path = if ($env:WRAPPER_WEB_PATH) { $env:WRAPPER_WEB_PATH } else { 'wrapper' }

try {
    tailscale serve --bg --set-path "/$Path" "http://127.0.0.1:$Port" | Out-Null
    Write-Host "Tailscale route configured on /$Path -> 127.0.0.1:$Port"
} catch {
    Write-Warning 'Unable to configure tailscale serve. Ensure Tailscale CLI is installed and authenticated.'
}

& $Python app.py
