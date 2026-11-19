# Reuse compatible runtimes; fall back to verified official user-local copies.
$script:runtimeRoot = Join-Path $env:LOCALAPPDATA 'ShunguangCompanion\runtimes'
$script:pythonVersion = '3.14.10'
$script:nodeVersion = '24.22.2'

function Get-FileSha256([string]$Path) {
    $stream = [IO.File]::OpenRead($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path))
    $digest = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($digest.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $digest.Dispose() }
}

function Get-VerifiedDownload([string]$Url, [string]$Target, [string]$Hash) {
    if ($Hash -notmatch '^[0-9a-f]{64}$') { throw 'Invalid official SHA-256.' }
    if ((Test-Path -LiteralPath $Target) -and (Get-FileSha256 $Target) -eq $Hash) { return }
    $partial = "$Target.partial"
    Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 300 -OutFile $partial
    if ((Get-FileSha256 $partial) -ne $Hash) { throw "SHA-256 verification failed: $Url" }
    Move-Item -LiteralPath $partial -Destination $Target -Force
}

function Initialize-ProjectPython([string]$PythonPath) {
    $cached = Join-Path $script:runtimeRoot "python-$script:pythonVersion\python.exe"
    if ($PythonPath -or (Test-Path -LiteralPath '.venv') -or (Test-Path -LiteralPath '.venv-rag')) {
        return Select-ProjectPython -PythonPath $PythonPath
    }
    try { return Select-ProjectPython } catch {
        if (-not $_.Exception.Message.StartsWith('No supported Python found.')) { throw }
    }
    if (Test-Path -LiteralPath $cached) { return Select-ProjectPython -PythonPath $cached }
    New-Item -ItemType Directory -Path $script:runtimeRoot -Force | Out-Null
    $name = "python-$script:pythonVersion-amd64.exe"
    $installer = Join-Path $script:runtimeRoot $name
    Write-Host "Preparing Python $script:pythonVersion for the current user."
    Get-VerifiedDownload "https://www.python.org/ftp/python/$script:pythonVersion/$name" $installer '92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965'
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'CN=Python Software Foundation(?:,|$)') {
        throw 'Python installer signature could not be verified.'
    }
    $target = Split-Path -Parent $cached
    $setup = Start-Process -FilePath $installer -ArgumentList @('/quiet', 'InstallAllUsers=0', "TargetDir=`"$target`"", 'PrependPath=0', 'Include_launcher=0', 'Include_test=0', 'Include_doc=0', 'Shortcuts=0') -Wait -PassThru -WindowStyle Hidden
    if ($setup.ExitCode -in @(1641, 3010)) { throw 'Restart Windows, then rerun Install.bat.' }
    if ($setup.ExitCode -ne 0) { throw "Python installation failed (exit $($setup.ExitCode))." }
    return Select-ProjectPython -PythonPath $cached
}

function Test-ProjectNode([string]$Executable) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $false }
    if (-not (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $Executable) 'npm.cmd') -PathType Leaf)) { return $false }
    try {
        $probe = & $Executable -p "[process.platform,process.arch,process.version].join(':')" 2>$null
        return $LASTEXITCODE -eq 0 -and $probe -match '^win32:x64:v24\.'
    } catch { return $false }
}

function Initialize-ProjectNode {
    $name = "node-v$script:nodeVersion-win-x64"
    $target = Join-Path $script:runtimeRoot $name
    $cached = Join-Path $target 'node.exe'
    $candidates = @((Get-Command node.exe -CommandType Application -All -ErrorAction SilentlyContinue).Source) + @($cached)
    foreach ($candidate in $candidates) {
        if (Test-ProjectNode $candidate) {
            $env:PATH = (Split-Path -Parent $candidate) + ';' + $env:PATH
            return
        }
    }
    if (Test-Path -LiteralPath $target) { throw "Incompatible Node directory. Move it aside and retry: $target" }
    New-Item -ItemType Directory -Path $script:runtimeRoot -Force | Out-Null
    $origin = "https://nodejs.org/dist/v$script:nodeVersion"
    Write-Host "Preparing Node.js $script:nodeVersion for the current user."
    $archive = Join-Path $script:runtimeRoot "$name.zip"
    # Pinned from this release's official SHASUMS256.txt; update version and digest together.
    Get-VerifiedDownload "$origin/$name.zip" $archive 'ca1bff5d8ead13c9f2ea404a176db46bd430704d5b5113734049fa365e7799e2'
    $stage = Join-Path $script:runtimeRoot ('.extract-' + [guid]::NewGuid().ToString('N'))
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $stage)
    $extracted = Join-Path $stage $name
    foreach ($file in @('node.exe','npm.cmd')) {
        if (-not (Test-Path -LiteralPath (Join-Path $extracted $file) -PathType Leaf)) {
            throw "Verified Node.js archive did not extract $file."
        }
    }
    if (-not (Test-ProjectNode (Join-Path $extracted 'node.exe'))) {
        throw 'Extracted node.exe could not run or did not report Windows x64 Node.js 24.'
    }
    Move-Item -LiteralPath $extracted -Destination $target
    Remove-Item -LiteralPath $stage
    $env:PATH = "$target;$env:PATH"
}
