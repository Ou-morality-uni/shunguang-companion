param([switch]$Cpu, [switch]$SkipFrontend, [ValidateSet('release','official')][string]$ModelSource = 'release')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try {
    $installArgs = @('scripts/install-project.py','--model-source',$ModelSource)
    if ($Cpu) { $installArgs += '--cpu' }
    if ($SkipFrontend) { $installArgs += '--skip-frontend' }
    if (Get-Command py.exe -ErrorAction SilentlyContinue) { & py.exe -3.11 @installArgs }
    elseif (Get-Command python.exe -ErrorAction SilentlyContinue) { & python.exe @installArgs }
    else { throw 'Python 3.11 is required. Install Python and Node.js 24, then retry.' }
    exit $LASTEXITCODE
} catch {
    Write-Host ('Installation failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
