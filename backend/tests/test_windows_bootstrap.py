"""Windows entry helpers exercised without installing software or using real user data."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell entry points')


def powershell(tmp_path, body):
    script = tmp_path / 'check.ps1'
    script.write_text("$ErrorActionPreference = 'Stop'\n" + body, encoding='utf-8-sig')
    return subprocess.run(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=30,
    )


def test_corrupt_runtime_download_is_not_published(tmp_path):
    helper = str(ROOT / 'scripts/windows-runtime.ps1').replace("'", "''")
    result = powershell(
        tmp_path,
        f"""
. '{helper}'
function Invoke-WebRequest {{ param($Uri,[switch]$UseBasicParsing,$TimeoutSec,$OutFile) [IO.File]::WriteAllText($OutFile,'corrupt') }}
$target = Join-Path $PSScriptRoot 'node.zip'
try {{ Get-VerifiedDownload 'https://nodejs.org/fixture.zip' $target ('0' * 64); exit 2 }}
catch {{ if (Test-Path -LiteralPath $target) {{ exit 3 }}; if ($_.Exception.Message -notmatch 'SHA-256 verification failed') {{ throw }}; exit 0 }}
""",
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / 'node.zip').exists()


def test_wizard_keeps_install_mode_qq_and_office_choices_independent(tmp_path):
    helper = str(ROOT / 'scripts/prepare-launch.ps1').replace("'", "''")
    result = powershell(
        tmp_path,
        f"""
. '{helper}'
$script:answers = [Collections.Generic.Queue[string]]::new()
@('2','1','2') | ForEach-Object {{ $script:answers.Enqueue($_) }}
function Read-Host {{ param($Prompt) return $script:answers.Dequeue() }}
$chosen = Show-InstallChoices
Write-Output ('RESULT:' + ($chosen | ConvertTo-Json -Compress))
""",
    )
    assert result.returncode == 0, result.stderr
    record = next(line.removeprefix('RESULT:') for line in result.stdout.splitlines() if line.startswith('RESULT:'))
    assert json.loads(record) == {'mode': 'lite', 'qq': False, 'office_guide': True}


def test_windows_entry_scripts_parse_without_running_installation(tmp_path):
    folder = str(ROOT / 'scripts').replace("'", "''")
    result = powershell(
        tmp_path,
        f"""
$failed = $false
Get-ChildItem -LiteralPath '{folder}' -Filter '*.ps1' | ForEach-Object {{
  $parseErrors = $null
  [Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$null,[ref]$parseErrors) | Out-Null
  if ($parseErrors) {{ $failed = $true; $parseErrors | ForEach-Object {{ Write-Output $_.Message }} }}
}}
if ($failed) {{ exit 1 }}
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_frontend_bundle_is_detected_before_browser_opens(tmp_path):
    helper = str(ROOT / 'scripts/prepare-launch.ps1').replace("'", "''")
    assets = tmp_path / 'frontend/dist/assets'
    assets.mkdir(parents=True)
    (assets.parent / 'index.html').write_text('<script type="module" src="/assets/app.js"></script>')
    result = powershell(
        tmp_path,
        f"""
. '{helper}'
Set-Location -LiteralPath $PSScriptRoot
$missing = Test-FrontendBuild
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'frontend/dist/assets/app.js'),'fixture')
@{{missing=$missing;complete=(Test-FrontendBuild)}} | ConvertTo-Json -Compress
""",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'missing': False, 'complete': True}


def test_running_environment_cannot_be_modified_by_second_process(tmp_path):
    from scripts.project_lock import environment_lock

    probe = 'from pathlib import Path; from scripts.project_lock import environment_lock; import sys; lock=environment_lock(Path(sys.argv[1])); lock.close()'
    with environment_lock(tmp_path):
        result = subprocess.run(
            [sys.executable, '-c', probe, str(tmp_path)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        assert result.returncode != 0
        assert 'already running or installing' in result.stderr
    result = subprocess.run([sys.executable, '-c', probe, str(tmp_path)], capture_output=True)
    assert result.returncode == 0


def test_selecting_no_qq_disables_existing_connection_without_erasing_token_or_policies(tmp_path):
    from backend.app.qq.models import Policy
    from backend.app.qq.repository import QQRepository

    repo = QQRepository(tmp_path / 'qq')
    repo.put('connection', {'enabled': True, 'bot_id': '10001', 'token_encrypted': 'opaque-preserved-token'})
    repo.save_policy('private', '30001', Policy(collect=True))
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/disable-local-qq.py')],
        capture_output=True,
        env={**os.environ, 'SHUNGUANG_DATA_DIR': str(tmp_path), 'SHUNGUANG_MODE': 'desktop'},
    )
    assert result.returncode == 0, result.stderr
    assert repo.connection().enabled is False
    assert repo.get('connection')['token_encrypted'] == 'opaque-preserved-token'
    assert repo.policy('private', '30001').collect is True


def test_install_choices_are_read_without_network_and_source_changes_invalidate_build(tmp_path):
    helper = str(ROOT / 'scripts/prepare-launch.ps1').replace("'", "''")
    names = [
        'backend/requirements.lock.txt',
        'frontend/package.json',
        'frontend/package-lock.json',
        'frontend/index.html',
        'scripts/install-project.py',
        'scripts/windows-runtime.ps1',
        'scripts/setup-project.py',
        'backend/requirements-rag.lock.txt',
        'scripts/download-rag-model.py',
        'frontend/src/main.tsx',
    ]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    preferences = tmp_path / 'data/install/preferences.json'
    preferences.parent.mkdir(parents=True)
    preferences.write_text('{"mode":"lite","qq":false}')
    result = powershell(
        tmp_path,
        f"""
. '{helper}'
Set-Location -LiteralPath $PSScriptRoot
$before = Get-InstallFingerprint
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'frontend/src/main.tsx'),'changed')
$after = Get-InstallFingerprint
$prefs = Read-InstallPreferences
@{{mode=$prefs.mode;qq=$prefs.qq;changed=($before -ne $after)}} | ConvertTo-Json -Compress
""",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'mode': 'lite', 'qq': False, 'changed': True}
