param([int]$Port = 8000, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$url = "http://127.0.0.1:$Port/"

function Test-AppReady {
    try {
        $page = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return $page.StatusCode -eq 200 -and $page.Content -match '<title>瞬光伴行'
    } catch { return $false }
}

try {
    if (Test-AppReady) {
        Write-Host '瞬光伴行已运行，正在打开页面。'
        Write-Host '日志在原来的后端窗口中。停止服务请关闭原后端窗口。'
        if (-not $NoBrowser) { Start-Process $url }
        exit 0
    }
    $socket = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $socket.BeginConnect('127.0.0.1', $Port, $null, $null)
        if ($connect.AsyncWaitHandle.WaitOne(500) -and $socket.Connected) {
            throw "$Port 端口已被占用，且未识别为本项目。请关闭占用该端口的程序后重试。"
        }
    } finally { $socket.Dispose() }
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        throw '缺少运行环境。请先按 README 运行 scripts/install.ps1，再双击本脚本。'
    }
    if (-not (Test-Path -LiteralPath 'frontend/dist/index.html')) {
        throw '缺少前端构建。请先按 README 完成安装与构建，再双击本脚本。'
    }
    if (-not (Test-Path -LiteralPath 'scripts/run-console.py')) {
        throw '缺少 scripts/run-console.py，请将本脚本放在完整项目的根目录。'
    }
    Write-Host '正在启动瞬光伴行，服务就绪后自动打开浏览器。'
    Write-Host "陪伴界面：$url"
    Write-Host '此窗口显示后端日志。关闭窗口即停止后端；Ctrl+C 可正常退出。'
    $browserJob = $null
    if (-not $NoBrowser) { $browserJob = Start-Job -ArgumentList $url -ScriptBlock {
        param($address)
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            try {
                $page = Invoke-WebRequest -Uri $address -UseBasicParsing -TimeoutSec 1
                if ($page.StatusCode -eq 200 -and $page.Content -match '<title>瞬光伴行') {
                    Start-Process $address
                    return
                }
            } catch {}
            Start-Sleep -Seconds 1
        }
        Write-Output "未能自动打开页面。请查看服务错误，或手动打开 $address。"
    } }
    try {
        & (Join-Path $projectRoot '.venv/Scripts/python.exe') -u (Join-Path $projectRoot 'scripts/run-console.py') --port $Port
        $result = $LASTEXITCODE
    } finally {
        if ($browserJob) {
            Stop-Job -Job $browserJob -ErrorAction SilentlyContinue
            Receive-Job -Job $browserJob -ErrorAction SilentlyContinue
            Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
        }
    }
    exit $result
} catch {
    Write-Host ('启动失败：' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
