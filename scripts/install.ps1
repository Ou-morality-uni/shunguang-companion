[CmdletBinding()]
param([switch]$Cpu, [switch]$SkipFrontend, [ValidateSet('release','official')][string]$ModelSource = 'release', [string]$PythonPath, [switch]$CheckPython, [switch]$Lite, [switch]$Full, [switch]$Bootstrap, [switch]$Setup, [switch]$Launch, [int]$Port = 8000)
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
        $installKnowledge = $Full -and -not $Bootstrap
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
    if (-not $installKnowledge) { $installArgs += '--lite' }
    Write-Host ('Using CPython ' + ($python.Info.version -join '.') + ' for the project environments.')
    Write-Host ('Python executable: ' + $python.Path)
    & $python.Path @installArgs
    $result = $LASTEXITCODE
    if ($result -eq 0) {
        if (-not $saved) { $saved = [PSCustomObject]@{ mode = 'lite'; qq = $false; office_guide = $false } }
        if ($installKnowledge) { $saved.mode = 'full' }
        if (-not $SkipFrontend) { $saved | Add-Member -NotePropertyName fingerprint -NotePropertyValue (Get-InstallFingerprint) -Force }
        $temporary = "$path.$([guid]::NewGuid().ToString('N')).tmp"
        [IO.File]::WriteAllText($temporary, ($saved | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        if ($corruptPreferences) { Copy-Item -LiteralPath $path -Destination "$path.corrupt-$([guid]::NewGuid().ToString('N'))" }
        Move-Item -LiteralPath $temporary -Destination $path -Force
        if (-not $SkipFrontend) { Write-Host '基础安装完成。可选服务请在网页的服务管理中配置。' }
    }
} catch {
    Write-Host ('Installation failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($launchLock) { $launchLock.Dispose() }
}
if ($result -eq 0 -and $Launch -and -not $SkipFrontend) {
    & (Join-Path $PSScriptRoot 'start-console.ps1') -Port $Port
    exit $LASTEXITCODE
}
exit $result
