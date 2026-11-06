param([Parameter(Mandatory = $true)][string]$ArchivedProjectPath)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = (Resolve-Path -LiteralPath $ArchivedProjectPath).Path
# Explicit selected assets only; no settings, chat database, cache or weights.
$mediaPaths = @('source/resources/character/avatar.png', 'source/resources/character/stickers', 'source/resources/assets/ye-shunguang', 'source/resources/voice/ye-shunguang/reference-original.mp4', 'source/resources/voice/ye-shunguang/reference-original.mp3')
foreach ($relative in $mediaPaths) {
    $sourcePath = Join-Path $sourceRoot $relative
    $targetPath = Join-Path $projectRoot $relative
    if (-not (Test-Path -LiteralPath $sourcePath)) { Write-Warning "缺少归档素材：$relative"; continue }
    if (Test-Path -LiteralPath $sourcePath -PathType Container) {
        New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
        Get-ChildItem -LiteralPath $sourcePath -File | ForEach-Object {
            $destination = Join-Path $targetPath $_.Name
            if (-not (Test-Path -LiteralPath $destination)) { Copy-Item -LiteralPath $_.FullName -Destination $destination }
        }
    } else {
        New-Item -ItemType Directory -Path (Split-Path -Parent $targetPath) -Force | Out-Null
        if (-not (Test-Path -LiteralPath $targetPath)) { Copy-Item -LiteralPath $sourcePath -Destination $targetPath }
    }
}
Write-Host '已导入缺失的本机归档素材；现有文件未覆盖。素材公开分发条件仍需自行确认。'
