# Sourced by the foreground launcher; no service or personal settings are changed here.
. (Join-Path $PSScriptRoot 'windows-runtime.ps1')

function Get-InstallFingerprint {
    $inputs = @('backend/requirements.lock.txt', 'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html', 'scripts/install-project.py', 'scripts/windows-runtime.ps1', 'scripts/setup-project.py')
    if (Test-Path -LiteralPath 'frontend/runtime-assets.ts') { $inputs += 'frontend/runtime-assets.ts' }
    $inputs += @(Get-ChildItem -LiteralPath 'frontend/src' -Recurse -File | ForEach-Object { $_.FullName })
    if (Test-Path -LiteralPath 'frontend/scripts') {
        $inputs += @(Get-ChildItem -LiteralPath 'frontend/scripts' -Recurse -File | ForEach-Object { $_.FullName })
    }
    $inputs += @(Get-ChildItem -LiteralPath 'frontend' -File | Where-Object { $_.Name -match '^(vite|tsconfig)' } | ForEach-Object { $_.FullName })
    $inputs += @('backend/requirements-rag.lock.txt', 'scripts/download-rag-model.py')
    $joined = (@($inputs | Sort-Object -Unique | ForEach-Object { Get-FileSha256 $_ }) -join '')
    $digest = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($digest.ComputeHash([Text.Encoding]::UTF8.GetBytes($joined)))).Replace('-','').ToLowerInvariant() }
    finally { $digest.Dispose() }
}

function Read-InstallPreferences {
    if (-not (Test-Path -LiteralPath 'data/install/preferences.json')) { return $null }
    try {
        $value = Get-Content -LiteralPath 'data/install/preferences.json' -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($value.mode -notin @('full','lite') -or $value.qq -isnot [bool]) { throw 'Invalid preferences' }
        return $value
    } catch { throw '安装记录损坏。保留 data，运行 Install.bat -Setup 修复记录。' }
}

function Test-FrontendBuild {
    $entry = 'frontend/dist/index.html'
    if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { return $false }
    $html = [IO.File]::ReadAllText((Join-Path (Get-Location) $entry))
    $references = [regex]::Matches($html, '(?:src|href)="(/assets/[^"?#]+)[^\"]*"')
    if ($references.Count -eq 0 -or $html -notmatch 'src="/assets/[^"?]+\.js') { return $false }
    foreach ($match in $references) {
        $asset = Join-Path 'frontend/dist' $match.Groups[1].Value.TrimStart('/')
        if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) { return $false }
    }
    return $true
}

function Assert-LaunchEnvironment {
    $preferences = Read-InstallPreferences
    if (-not $preferences) { throw '尚未完成安装。请先运行 Install.bat。' }
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe' -PathType Leaf)) {
        throw '缺少项目的 Python 虚拟环境。请运行 Install.bat 修复。'
    }
    if (-not (Test-FrontendBuild)) { throw '前端构建产物缺失或不完整。请运行 Install.bat。' }
    try { $fingerprint = Get-InstallFingerprint }
    catch { throw ('无法验证安装输入，请检查项目文件并运行 Install.bat。' + $_.Exception.Message) }
    if ($preferences.fingerprint -ne $fingerprint) {
        throw '安装未完成或依赖／前端输入已变更。请运行 Install.bat 更新。'
    }
    try {
        & '.\.venv\Scripts\python.exe' -I -c 'import fastapi,uvicorn,langchain_openai,imageio_ffmpeg' 2>$null
        $ready = $LASTEXITCODE -eq 0
    } catch { $ready = $false }
    if (-not $ready) { throw '项目 Python 环境无法运行或缺少依赖。请运行 Install.bat 修复。' }
}
