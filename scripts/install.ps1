[CmdletBinding()]
param([switch]$Cpu, [switch]$SkipFrontend, [ValidateSet('release','official')][string]$ModelSource = 'release', [string]$PythonPath, [switch]$CheckPython, [switch]$Lite, [switch]$Full, [switch]$Bootstrap, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try {
    if ($Full -and $Lite) { throw 'Choose either Full or Lite.' }
    if (-not $Full -and -not $Lite -and -not $CheckPython) {
        . (Join-Path $PSScriptRoot 'prepare-launch.ps1')
        $previous = Read-InstallPreferences
        if ($previous -and $previous.mode -eq 'lite') { $Lite = $true }
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
        . (Join-Path $PSScriptRoot 'prepare-launch.ps1')
        try { $saved = Read-InstallPreferences }
        catch {
            if (-not $Full -and -not $Lite) { throw }
            $corrupt = Join-Path (Get-Location) ('data/install/preferences.json.corrupt-' + [guid]::NewGuid().ToString('N'))
            Move-Item -LiteralPath 'data/install/preferences.json' -Destination $corrupt
            $saved = $null
        }
        if (-not $saved) { $saved = [PSCustomObject]@{ mode = 'full'; qq = $false; office_guide = $false } }
        $saved.mode = if ($Lite) { 'lite' } else { 'full' }
        if (-not $SkipFrontend) { $saved | Add-Member -NotePropertyName fingerprint -NotePropertyValue (Get-InstallFingerprint) -Force }
        $path = Join-Path (Get-Location) 'data/install/preferences.json'
        $temporary = "$path.$([guid]::NewGuid().ToString('N')).tmp"
        [IO.File]::WriteAllText($temporary, ($saved | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $path -Force
    }
    exit $result
} catch {
    Write-Host ('Installation failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
