# Sourced by the foreground launcher; no service or personal settings are changed here.
. (Join-Path $PSScriptRoot 'windows-runtime.ps1')

function Get-InstallFingerprint {
    $inputs = @('backend/requirements.lock.txt', 'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html', 'scripts/install-project.py', 'scripts/windows-runtime.ps1', 'scripts/setup-project.py')
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
    } catch { throw '安装选择记录损坏。保留 data，使用 Start_up.bat -Setup 重新选择。' }
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

function Show-InstallChoices {
    Write-Host '首次安装 / 重新配置：所有模型服务仍需你填写自己的 API。'
    Write-Host '1 完整安装：包含本地知识检索，需下载数 GB，至少 12 GiB 磁盘空间。'
    Write-Host '2 轻量安装：保留聊天、记忆、云端模型与可选 QQ，不下载向量模型，至少 3 GiB 空间。'
    do { $choice = Read-Host '选择安装模式 [1/2]' } while ($choice -notin @('1','2'))
    Write-Host 'QQ 接入使用第三方桥接，可能受协议变化或账号风控影响，不保证持续可用。'
    Write-Host '需自行安装 NapCat、登录本人账号，按联系人/群授权；模型/识图/摘要可能产生费用。'
    do { $qq = Read-Host '1 暂不接入 QQ（关闭已有连接，保留记录，不下载桥接） / 2 查看 QQ 接入指南' } while ($qq -notin @('1','2'))
    if ($qq -eq '2') {
        Write-Host 'QQ 指南：docs/qq-setup.md'
        Write-Host '官方桥接入口：https://napneko.github.io/guide/boot/Shell'
    }
    Write-Host 'LibreOffice 仅用于 Office 页面预览、转 PDF 和公式重算；普通聊天与 QQ 无需安装。'
    do { $office = Read-Host '1 暂不安装 / 2 查看官方安装指南' } while ($office -notin @('1','2'))
    if ($office -eq '2') {
        Write-Host '指南：versions/0.6.1/LibreOffice-install.md'
        Write-Host '官方下载：https://www.libreoffice.org/download/download-libreoffice/'
    }
    return [PSCustomObject]@{ mode = $(if ($choice -eq '1') { 'full' } else { 'lite' }); qq = ($qq -eq '2'); office_guide = ($office -eq '2') }
}

function Initialize-LaunchEnvironment([switch]$Setup, [int]$Port) {
    $preferences = if ($Setup) { $null } else { Read-InstallPreferences }
    $freshChoices = $Setup -or -not $preferences
    if ($freshChoices) { $preferences = Show-InstallChoices }
    $fingerprint = Get-InstallFingerprint
    $requiresInstall = $freshChoices -or -not (Test-Path -LiteralPath '.venv/Scripts/python.exe') -or -not (Test-FrontendBuild)
    if (-not $freshChoices) {
        $requiresInstall = $requiresInstall -or $preferences.fingerprint -ne $fingerprint
        if (-not $requiresInstall) {
            & '.\.venv\Scripts\python.exe' -I -c 'import fastapi,uvicorn,langchain_openai,imageio_ffmpeg' 2>$null
            $requiresInstall = $LASTEXITCODE -ne 0
        }
        if ($requiresInstall) {
            Write-Host '依赖或前端输入已变更／环境不完整，需要更新；已有 data 保留。'
            if ((Read-Host '输入 Y 更新，其他输入退出') -notmatch '^[yY]$') { throw '尚未更新，请准备好后重新启动。' }
        }
    }
    if ($requiresInstall) {
        $installArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'install.ps1'),'-Bootstrap','-Port', $Port)
        if ($preferences.mode -eq 'lite') { $installArgs += '-Lite' } else { $installArgs += '-Full' }
        & powershell.exe @installArgs
        if ($LASTEXITCODE -ne 0) { throw '安装未完成，请修复窗口显示的问题后重试；安装选择尚未覆盖。' }
        $preferences | Add-Member -NotePropertyName fingerprint -NotePropertyValue $fingerprint -Force
        New-Item -ItemType Directory -Path 'data/install' -Force | Out-Null
        $temporary = Join-Path 'data/install' ('preferences-' + [guid]::NewGuid().ToString('N') + '.tmp')
        [IO.File]::WriteAllText((Join-Path (Get-Location) $temporary), ($preferences | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination 'data/install/preferences.json' -Force
    }
    if ($freshChoices -and -not $preferences.qq) {
        & '.\.venv\Scripts\python.exe' 'scripts/disable-local-qq.py'
        if ($LASTEXITCODE -ne 0) { throw 'QQ 关闭设置未完成，请在网页检查连接开关后重试。' }
    }
    if ($preferences.qq) { Write-Host 'QQ：按 docs/qq-setup.md 安装桥接后，在网页“QQ 接入”配置。' }
}
