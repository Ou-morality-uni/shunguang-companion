[CmdletBinding()]
param([switch]$Cpu, [switch]$SkipFrontend, [ValidateSet('release','official')][string]$ModelSource = 'release', [string]$PythonPath, [switch]$CheckPython, [switch]$Lite, [switch]$Full, [switch]$Bootstrap, [switch]$Setup, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try {
    if ($Full -and $Lite) { throw 'Choose either Full or Lite.' }
    if ($Setup -and ($Full -or $Lite)) { throw 'Use -Setup to select the mode interactively, or pass -Full or -Lite without -Setup.' }
    if (-not $CheckPython) {
        New-Item -ItemType Directory -Path 'data/install' -Force | Out-Null
        $path = Join-Path (Get-Location) 'data/install/preferences.json'
        $lockPath = Join-Path (Get-Location) 'data/install/launcher.lock'
        try { $launchLock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
        catch { throw '另一个窗口正在安装或运行本项目，请先正常停止后再安装。' }
        . (Join-Path $PSScriptRoot 'prepare-launch.ps1')
        $corruptPreferences = $false
        try { $saved = Read-InstallPreferences }
        catch {
            if (-not ($Setup -or $Full -or $Lite)) { throw }
            $corruptPreferences = $true
        }
        $choose = $Setup -or ($Bootstrap -and -not ($saved -or $Full -or $Lite))
        if ($choose) { $saved = Show-InstallChoices }
        if (-not $Full -and -not $Lite -and $saved -and $saved.mode -eq 'lite') { $Lite = $true }
    }
    . (Join-Path $PSScriptRoot 'select-python.ps1')
    if ($Bootstrap -and -not $CheckPython) {
        . (Join-Path $PSScriptRoot 'windows-runtime.ps1')
        $mutex = [System.Threading.Mutex]::new($false, 'Local\ShunguangCompanionRuntimeSetup')
        $owned = $false
        try {
            try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
            if (-not $owned) { throw 'Another window is preparing runtimes. Wait for it to finish and retry.' }
            $python = Initialize-ProjectPython $PythonPath
            if (-not $SkipFrontend) { Initialize-ProjectNode }
        } finally {
            if ($owned) { $mutex.ReleaseMutex() }
            $mutex.Dispose()
        }
    } else {
        $python = Select-ProjectPython -PythonPath $PythonPath
    }
    if ($CheckPython) { $python.Info | ConvertTo-Json -Compress -Depth 3; exit 0 }
    $installArgs = @('scripts/install-project.py','--model-source',$ModelSource,'--port',$Port)
    if ($Cpu) { $installArgs += '--cpu' }
    if ($SkipFrontend) { $installArgs += '--skip-frontend' }
    if ($Lite) { $installArgs += '--lite' }
    Write-Host ('Using CPython ' + ($python.Info.version -join '.') + ' for the project environments.')
    & $python.Path @installArgs
    $result = $LASTEXITCODE
    if ($result -eq 0) {
        if (-not $saved) { $saved = [PSCustomObject]@{ mode = 'full'; qq = $false; office_guide = $false } }
        $saved.mode = if ($Lite) { 'lite' } else { 'full' }
        if (-not $SkipFrontend) { $saved | Add-Member -NotePropertyName fingerprint -NotePropertyValue (Get-InstallFingerprint) -Force }
        if ($choose -and -not $saved.qq) {
            & '.\.venv\Scripts\python.exe' 'scripts/disable-local-qq.py'
            if ($LASTEXITCODE -ne 0) { throw 'QQ 关闭设置未完成，请检查错误后重新运行 Install.bat。' }
        }
        $temporary = "$path.$([guid]::NewGuid().ToString('N')).tmp"
        [IO.File]::WriteAllText($temporary, ($saved | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        if ($corruptPreferences) { Copy-Item -LiteralPath $path -Destination "$path.corrupt-$([guid]::NewGuid().ToString('N'))" }
        Move-Item -LiteralPath $temporary -Destination $path -Force
        if ($choose -and $saved.qq) { Write-Host 'QQ：按 docs/qq-setup.md 安装桥接后，在网页“QQ 接入”配置。' }
        if (-not $SkipFrontend) { Write-Host '安装完成。现在可以双击 Start_up.bat 启动。' }
    }
    exit $result
} catch {
    Write-Host ('Installation failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($launchLock) { $launchLock.Dispose() }
}
