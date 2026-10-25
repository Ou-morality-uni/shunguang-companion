[CmdletBinding()]
param([switch]$Cpu, [switch]$SkipModel, [ValidateSet('release','official')][string]$ModelSource = 'release', [string]$PythonPath, [switch]$CheckPython)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try {
    . (Join-Path $PSScriptRoot 'select-python.ps1')
    $python = Select-ProjectPython -PythonPath $PythonPath
    if ($CheckPython) { $python.Info | ConvertTo-Json -Compress -Depth 3; exit 0 }
    $installArgs = @('scripts/install-project.py','--model-source',$ModelSource)
    $installArgs += '--rag-only'
    if ($Cpu) { $installArgs += '--cpu' }
    if ($SkipModel) { $installArgs += '--skip-model' }
    Write-Host ('Using CPython ' + ($python.Info.version -join '.') + ' for the project environments.')
    & $python.Path @installArgs
    exit $LASTEXITCODE
} catch {
    Write-Host ('Installation failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
