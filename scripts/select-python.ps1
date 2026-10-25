# Shared by both Windows installers. Probe real interpreters without installing them.
function Get-ProjectPythonInfo {
    param([string]$Executable)
    try {
        $result = & $Executable -I (Join-Path $PSScriptRoot 'install-project.py') --python-info 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $info = ($result -join "`n") | ConvertFrom-Json
        if ($info.supported -and $info.version.Count -ge 2) { return $info }
    } catch { }
    return $null
}

function Select-ProjectPython {
    param([string]$PythonPath)
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $existing = @()
    foreach ($name in @('.venv', '.venv-rag')) {
        $folder = Join-Path $projectRoot $name
        if (-not (Test-Path -LiteralPath $folder)) { continue }
        $executable = Join-Path $folder 'Scripts/python.exe'
        $info = Get-ProjectPythonInfo $executable
        if (-not $info) {
            throw "$name is incomplete or unsupported. Preserve your data and move this environment aside before retrying. Supported: standard CPython 3.11-3.14, Windows x64."
        }
        $existing += [PSCustomObject]@{ Path = $executable; Info = $info }
    }
    if ($existing.Count -gt 1 -and (($existing[0].Info.version[0..1] -join '.') -ne ($existing[1].Info.version[0..1] -join '.'))) {
        throw '.venv and .venv-rag use different Python versions. Preserve data and resolve the environment mismatch before installing.'
    }
    if ($PythonPath) {
        $resolved = Get-Command $PythonPath -CommandType Application -ErrorAction SilentlyContinue
        if (-not $resolved) { throw 'The requested Python executable was not found.' }
        $info = Get-ProjectPythonInfo $resolved.Source
        if (-not $info) { throw 'The requested interpreter is unsupported. Use stable standard CPython 3.11-3.14, Windows x64 (not free-threaded).' }
        if ($existing.Count -and (($existing[0].Info.version[0..1] -join '.') -ne ($info.version[0..1] -join '.'))) {
            throw 'The requested Python conflicts with an existing environment. Preserve data and move the old environments aside before selecting another version.'
        }
        return [PSCustomObject]@{ Path = $resolved.Source; Info = $info }
    }
    if ($existing.Count) { return $existing[0] }

    $candidates = @()
    $launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($launcher) {
        # Listing avoids Python install manager's automatic download on a missing version.
        try {
            $listing = & $launcher.Source -0p 2>$null
            foreach ($line in $listing) {
                if ($line -match '^\s*-(?:V:)?\S+\s+\*?\s*(.+?\.exe)\s*$') { $candidates += $Matches[1] }
            }
        } catch { }
    }
    foreach ($command in @('python.exe', 'python3.exe')) {
        $matchesOnPath = @(Get-Command $command -CommandType Application -All -ErrorAction SilentlyContinue)
        foreach ($match in $matchesOnPath) {
            if ($match.Source -notmatch '\\WindowsApps\\') { $candidates += $match.Source }
        }
    }
    $supported = @()
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        $info = Get-ProjectPythonInfo $candidate
        if ($info) { $supported += [PSCustomObject]@{ Path = $candidate; Info = $info } }
    }
    if (-not $supported.Count) {
        throw 'No supported Python found. Install standard CPython 3.11, 3.12, 3.13 or 3.14 (Windows x64), or pass -PythonPath with the full path to python.exe. Node.js 24 is also required for a full installation.'
    }
    return ($supported | Sort-Object -Property @{ Expression = { [int]$_.Info.version[1] }; Descending = $true }, @{ Expression = { [int]$_.Info.version[2] }; Descending = $true } | Select-Object -First 1)
}
