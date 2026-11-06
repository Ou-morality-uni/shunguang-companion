$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先按照 README 创建 .venv 并安装依赖。' }
$env:SHUNGUANG_LAN_MODE = '0'
& $pythonPath -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log
exit $LASTEXITCODE
