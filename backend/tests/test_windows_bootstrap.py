"""Windows entry helpers exercised without installing software or using real user data."""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import venv
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def run_entry(tmp_path, entry, *arguments, env=None):
    scripts = tmp_path / 'scripts'
    scripts.mkdir(exist_ok=True)
    for name in ('start-console.ps1', 'prepare-launch.ps1', 'windows-runtime.ps1', 'install.ps1'):
        if not (scripts / name).exists():
            shutil.copyfile(ROOT / 'scripts' / name, scripts / name)
    shutil.copyfile(ROOT / entry, tmp_path / entry)
    return subprocess.run(
        ['cmd.exe', '/d', '/c', entry, *arguments],
        cwd=tmp_path,
        input='\n',
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        env={**os.environ, 'SHUNGUANG_INSTALL_NO_PAUSE': '1', **(env or {})},
        timeout=15,
    )


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return str(listener.getsockname()[1])


@pytest.mark.parametrize('arguments', [(), ('-Setup',)])
def test_uninstalled_start_exits_without_calling_install(tmp_path, arguments):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    (scripts / 'install.ps1').write_text("Set-Content 'install-called' yes; exit 1")
    helper = (ROOT / 'scripts/prepare-launch.ps1').read_text(encoding='utf-8-sig')
    (scripts / 'prepare-launch.ps1').write_text(
        helper + "\nfunction Show-InstallChoices { throw 'Startup entered the installation wizard.' }\n",
        encoding='utf-8-sig',
    )
    result = run_entry(tmp_path, 'Start_up.bat', '-NoBrowser', '-Port', free_port(), *arguments)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Install.bat' in result.stdout
    assert '选择安装模式' not in result.stdout
    assert not (tmp_path / 'install-called').exists()
    assert not (tmp_path / 'data/install/preferences.json').exists()


@pytest.mark.parametrize(
    ('state', 'message'),
    [
        ('corrupt', '安装选择记录损坏'),
        ('no-python', '缺少项目的 Python 虚拟环境'),
        ('no-bundle', '前端构建产物缺失'),
        ('outdated', '输入已变更'),
        ('broken-python', 'Python 环境无法运行'),
    ],
)
def test_start_only_checks_incomplete_installation(tmp_path, state, message):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    (scripts / 'install.ps1').write_text("Set-Content 'install-called' yes; exit 1")
    helper = (ROOT / 'scripts/prepare-launch.ps1').read_text(encoding='utf-8-sig')
    (scripts / 'prepare-launch.ps1').write_text(
        helper + "\nfunction Get-InstallFingerprint { return 'current' }\n",
        encoding='utf-8-sig',
    )
    preference = tmp_path / 'data/install/preferences.json'
    preference.parent.mkdir(parents=True)
    previous = (
        'invalid'
        if state == 'corrupt'
        else json.dumps({'mode': 'lite', 'qq': False, 'fingerprint': 'old' if state == 'outdated' else 'current'})
    )
    preference.write_text(previous)
    python = tmp_path / '.venv/Scripts/python.exe'
    if state != 'no-python':
        python.parent.mkdir(parents=True)
        python.touch()
    if state != 'no-bundle':
        assets = tmp_path / 'frontend/dist/assets'
        assets.mkdir(parents=True)
        (assets.parent / 'index.html').write_text('<script type="module" src="/assets/app.js"></script>')
        (assets / 'app.js').touch()
    result = run_entry(tmp_path, 'Start_up.bat', '-NoBrowser', '-Port', free_port())
    assert result.returncode == 1, result.stdout + result.stderr
    assert message in result.stdout
    assert 'Install.bat' in result.stdout
    assert preference.read_text() == previous
    assert not (tmp_path / 'install-called').exists()


def test_ready_start_runs_the_foreground_entry_on_the_requested_port(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    helper = (ROOT / 'scripts/prepare-launch.ps1').read_text(encoding='utf-8-sig')
    (scripts / 'prepare-launch.ps1').write_text(
        helper + "\nfunction Get-InstallFingerprint { return 'current' }\n",
        encoding='utf-8-sig',
    )
    (scripts / 'run-console.py').write_text(
        "import sys\nfrom pathlib import Path\nPath('started').write_text(' '.join(sys.argv[1:]))\n"
    )
    preference = tmp_path / 'data/install/preferences.json'
    preference.parent.mkdir(parents=True)
    preference.write_text('{"mode":"lite","qq":false,"fingerprint":"current"}')
    venv.create(tmp_path / '.venv')
    packages = tmp_path / '.venv/Lib/site-packages'
    for dependency in ('fastapi', 'uvicorn', 'langchain_openai', 'imageio_ffmpeg'):
        (packages / f'{dependency}.py').touch()
    assets = tmp_path / 'frontend/dist/assets'
    assets.mkdir(parents=True)
    (assets.parent / 'index.html').write_text('<script type="module" src="/assets/app.js"></script>')
    (assets / 'app.js').touch()
    port = free_port()
    result = run_entry(tmp_path, 'Start_up.bat', '-NoBrowser', '-Port', port)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / 'started').read_text() == f'--port {port}'


@pytest.mark.parametrize('project', [False, True])
def test_start_does_not_replace_a_listening_service(tmp_path, project):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = (
                b'{"status":"ok","version":"0.0.1"}'
                if self.path == '/api/health'
                else ('<title>瞬光伴行' if project else '<title>Other service').encode()
            )
            self.send_response(200)
            self.send_header(
                'Content-Type', 'application/json' if self.path == '/api/health' else 'text/html; charset=utf-8'
            )
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        try:
            result = run_entry(tmp_path, 'Start_up.bat', '-NoBrowser', '-Port', str(server.server_port))
            assert result.returncode == (0 if project else 1), result.stdout + result.stderr
            assert ('已运行' if project else '端口已被占用') in result.stdout
        finally:
            server.shutdown()
            serving.join(timeout=5)
    assert not (tmp_path / 'data').exists()


def test_install_entry_owns_first_run_and_setup_choices(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    helper = (ROOT / 'scripts/prepare-launch.ps1').read_text(encoding='utf-8-sig')
    (scripts / 'prepare-launch.ps1').write_text(
        helper
        + """
$script:answers = [Collections.Generic.Queue[string]]::new()
@('2','2','1') | ForEach-Object { $script:answers.Enqueue($_) }
function Read-Host { param($Prompt) return $script:answers.Dequeue() }
function Get-InstallFingerprint { return 'fixture-fingerprint' }
""",
        encoding='utf-8-sig',
    )
    (scripts / 'select-python.ps1').touch()
    (scripts / 'windows-runtime.ps1').write_text(
        """
function Initialize-ProjectPython {
    return @{ Path = $env:TEST_PYTHON; Info = @{ version = @(3,13,0) } }
}
function Initialize-ProjectNode {}
"""
    )
    (scripts / 'install-project.py').write_text(
        'import os, sys\n'
        'from pathlib import Path\n'
        "Path('installed-mode').write_text('lite' if '--lite' in sys.argv else 'full')\n"
        "sys.exit(int(os.environ.get('TEST_INSTALL_FAILURE', '0')))\n"
    )
    preferences = tmp_path / 'data/install/preferences.json'
    preferences.parent.mkdir(parents=True)
    env = {'TEST_PYTHON': sys.executable}
    first = run_entry(tmp_path, 'Install.bat', env=env)
    assert first.returncode == 0, first.stdout + first.stderr
    assert (tmp_path / 'installed-mode').read_text() == 'lite'
    assert 'Start_up.bat' in first.stdout
    assert json.loads(preferences.read_text()) == {
        'mode': 'lite',
        'qq': True,
        'office_guide': False,
        'fingerprint': 'fixture-fingerprint',
    }
    first_preferences = preferences.read_bytes()
    failed = run_entry(tmp_path, 'Install.bat', '-Full', env={**env, 'TEST_INSTALL_FAILURE': '1'})
    assert failed.returncode == 1
    assert preferences.read_bytes() == first_preferences
    repaired = run_entry(tmp_path, 'Install.bat', env=env)
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert '选择安装模式' not in repaired.stdout
    assert (tmp_path / 'installed-mode').read_text() == 'lite'
    preferences.write_text('bad-record')
    setup = run_entry(tmp_path, 'Install.bat', '-Setup', env=env)
    assert setup.returncode == 0, setup.stdout + setup.stderr
    assert json.loads(preferences.read_text())['mode'] == 'lite'
    assert next(preferences.parent.glob('preferences.json.corrupt-*')).read_text() == 'bad-record'


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


@pytest.mark.parametrize(
    'discover',
    ['registered', 'missing', 'cached', 'bad-hash', 'bad-signature', 'install-fails', 'check-missing'],
)
def test_install_entry_python_selection(tmp_path, discover):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copyfile(ROOT / 'scripts/select-python.ps1', scripts / 'select-python.ps1')
    runtime = (ROOT / 'scripts/windows-runtime.ps1').read_text(encoding='utf-8-sig')
    (scripts / 'windows-runtime.ps1').write_text(
        runtime
        + r"""
function Get-Command {
    param($Name, $CommandType, [switch]$All, $ErrorAction)
    if ($Name -eq 'py.exe' -and $env:TEST_DISCOVERY -eq 'registered') {
        return @{ Source = 'Get-TestPythonListing' }
    }
    if ($Name -like '*\python.exe' -and (Test-Path -LiteralPath $Name -PathType Leaf)) {
        return @{ Source = $env:TEST_PYTHON }
    }
}
function Get-TestPythonListing {
    ' -V:3.12 * Get-TestPython312.exe'
    ' -V:3.11   Get-TestPython311.exe'
    ' -V:3.15   Get-TestPython315.exe'
}
function Get-TestPython312.exe {
    $global:LASTEXITCODE = 0
    if ($args -contains '--python-info') { '{"supported":true,"version":[3,12,10]}' }
}
function Get-TestPython311.exe {
    $global:LASTEXITCODE = 0
    if ($args -contains '--python-info') { '{"supported":true,"version":[3,11,9]}' }
}
function Get-TestPython315.exe {
    $global:LASTEXITCODE = 0
    '{"supported":false,"version":[3,15,0]}'
}
function Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec, $OutFile)
    Write-Host "Download: $Uri"
    [IO.File]::WriteAllText($OutFile, 'fixture')
}
function Get-FileSha256 {
    param($Path)
    return $env:TEST_SHA256
}
function Get-AuthenticodeSignature {
    param($LiteralPath)
    $status = if ($env:TEST_DISCOVERY -eq 'bad-signature') { 'NotSigned' } else { 'Valid' }
    return @{ Status = $status; SignerCertificate = @{ Subject = 'CN=Python Software Foundation' } }
}
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru, $WindowStyle)
    Write-Host "Executing installer: $FilePath"
    if ($env:TEST_DISCOVERY -eq 'install-fails') { return @{ ExitCode = 1603 } }
    $target = ($ArgumentList | Where-Object { $_ -like 'TargetDir=*' }).Split('=', 2)[1].Trim('"')
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $target 'python.exe') | Out-Null
    return @{ ExitCode = 0 }
}
""",
        encoding='utf-8-sig',
    )
    (scripts / 'install-project.py').write_text(
        """import sys
if '--python-info' in sys.argv:
    print('{"supported":true,"version":[3,14,10]}')
""",
        encoding='utf-8',
    )
    local_app_data = tmp_path / 'local'
    cached = local_app_data / 'ShunguangCompanion/runtimes/python-3.14.10/python.exe'
    if discover == 'cached':
        cached.parent.mkdir(parents=True)
        cached.touch()
    env = {
        'LOCALAPPDATA': str(local_app_data),
        'TEST_DISCOVERY': discover,
        'TEST_PYTHON': sys.executable,
        'TEST_SHA256': (
            '0' * 64 if discover == 'bad-hash' else '92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965'
        ),
    }
    arguments = ('-CheckPython',) if discover == 'check-missing' else ('-Lite', '-SkipFrontend')
    if discover == 'check-missing':
        (scripts / 'select-python.ps1').write_text(
            'function Get-Command { param($Name, $CommandType, [switch]$All, $ErrorAction) }\n'
            + (scripts / 'select-python.ps1').read_text(encoding='utf-8-sig'),
            encoding='utf-8-sig',
        )
    result = run_entry(tmp_path, 'Install.bat', *arguments, env=env)
    if discover == 'check-missing':
        assert result.returncode == 1
        assert 'No supported Python found.' in result.stdout
        assert 'Download:' not in result.stdout
        assert not local_app_data.exists()
        return
    if discover == 'registered':
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'Using CPython 3.12.10' in result.stdout
        assert 'Get-TestPython312.exe' in result.stdout
        assert 'Download:' not in result.stdout
        return
    if discover != 'cached':
        assert 'Download: https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe' in result.stdout
    else:
        assert 'Download:' not in result.stdout
    if discover == 'bad-hash':
        assert result.returncode == 1
        assert 'SHA-256 verification failed' in result.stdout
        assert 'Executing installer:' not in result.stdout
    elif discover == 'bad-signature':
        assert result.returncode == 1
        assert 'signature could not be verified' in result.stdout
        assert 'Executing installer:' not in result.stdout
    elif discover == 'install-fails':
        assert result.returncode == 1
        assert 'exit 1603' in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'Using CPython 3.14.10' in result.stdout
        assert cached.is_file()


def test_compatible_node_is_detected_by_windows_powershell(tmp_path):
    node = shutil.which('node.exe')
    if not node or not Path(node).with_name('npm.cmd').is_file():
        pytest.skip('Node.js and npm are required for the real PowerShell probe')
    probe = subprocess.check_output(
        [node, '-p', "[process.platform,process.arch,process.version].join(':')"], text=True
    )
    if not probe.startswith('win32:x64:v24.'):
        pytest.skip('The Windows bootstrap supports x64 Node.js 24')
    helper = str(ROOT / 'scripts/windows-runtime.ps1').replace("'", "''")
    executable = node.replace("'", "''")
    result = powershell(
        tmp_path,
        f"""
. '{helper}'
function Get-VerifiedDownload {{ throw 'A working Node.js 24 should not require a download.' }}
$env:PATH = Split-Path -Parent '{executable}'
Initialize-ProjectNode
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ('include_npm', 'message'),
    [(False, 'did not extract npm.cmd'), (True, 'could not run or did not report')],
)
def test_node_bootstrap_distinguishes_incomplete_extraction_from_failed_execution(tmp_path, include_npm, message):
    with zipfile.ZipFile(tmp_path / 'fixture.zip', 'w') as archive:
        archive.writestr('node-v24.22.2-win-x64/node.exe', 'not executable')
        if include_npm:
            archive.writestr('node-v24.22.2-win-x64/npm.cmd', '')
    helper = str(ROOT / 'scripts/windows-runtime.ps1').replace("'", "''")
    result = powershell(
        tmp_path,
        f"""
$env:LOCALAPPDATA = $PSScriptRoot
$env:PATH = ''
. '{helper}'
function Get-VerifiedDownload {{
    param($Url, $Target, $Hash)
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'fixture.zip') -Destination $Target
}}
Initialize-ProjectNode
""",
    )
    assert result.returncode != 0
    assert message in result.stderr
    assert not (tmp_path / 'ShunguangCompanion/runtimes/node-v24.22.2-win-x64').exists()


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
