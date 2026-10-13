param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先运行 scripts/install.ps1。' }
if (-not (Test-Path -LiteralPath 'frontend/dist/index.html')) { throw '请先运行 npm --prefix frontend run build。' }
$env:SHUNGUANG_LAN_MODE = '0'
Write-Host "本机访问：http://127.0.0.1:$Port"
& $pythonPath -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port --no-access-log
exit $LASTEXITCODE
