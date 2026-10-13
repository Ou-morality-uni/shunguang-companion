param([int]$Port = 8000, [switch]$ResetPassword)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先运行 scripts/install.ps1。' }
if (-not (Test-Path -LiteralPath 'frontend/dist/index.html')) { throw '请先运行 npm --prefix frontend run build。' }
if ($ResetPassword -or -not (Test-Path -LiteralPath 'data/access.json')) {
    & $pythonPath scripts/setup-access.py
    if ($LASTEXITCODE -ne 0) { throw '局域网口令未设置，服务没有开放。' }
}
$env:SHUNGUANG_LAN_MODE = '1'
$addresses = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress)
$env:SHUNGUANG_ALLOWED_HOSTS = $addresses -join ','
Write-Host '同一 Wi-Fi 的手机浏览器打开以下电脑地址，输入刚设置的访问口令：'
foreach ($address in $addresses) { Write-Host "http://${address}:$Port" }
Write-Host '仅在可信局域网使用。脚本不修改防火墙，不开放公网；关闭终端即停止服务。'
& $pythonPath -m uvicorn backend.app.main:app --host 0.0.0.0 --port $Port --no-access-log
exit $LASTEXITCODE
