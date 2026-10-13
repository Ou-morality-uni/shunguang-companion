param([switch]$SkipFrontend)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 3.11 虚拟环境失败。' }
}
& ./.venv/Scripts/python.exe -m pip install -r backend/requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败。' }
if (-not $SkipFrontend) {
    npm --prefix frontend ci
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
    npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
}
Write-Host '应用安装完成。本地检索请按 RAG 安装说明运行独立安装脚本。'
