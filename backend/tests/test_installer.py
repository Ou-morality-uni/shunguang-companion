"""Installer safety and recovery tests; real release/inference checks are separate."""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    return instance


model = module('installer_model', 'download-rag-model.py')
setup = module('installer_setup', 'setup-project.py')
installer = module('installer_entry', 'install-project.py')


def record(body=b'model component'):
    return {
        'name': 'model.zip',
        'url': 'https://github.com/example/model.zip',
        'bytes': len(body),
        'sha256': hashlib.sha256(body).hexdigest(),
    }


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


def test_model_download_resumes_verified_partial(tmp_path, monkeypatch):
    body = b'abcdefghijk'
    (tmp_path / 'model.zip.partial').write_bytes(body[:4])

    def fetch(request, timeout):
        assert request.headers['Range'] == 'bytes=4-'
        return Response(body[4:], 206, {'Content-Range': 'bytes 4-10/11'})

    monkeypatch.setattr(model.urllib.request, 'urlopen', fetch)
    assert model.fetch_asset(record(body), tmp_path).read_bytes() == body


def test_server_ignoring_range_restarts_download(tmp_path, monkeypatch):
    body = b'abcdefghijk'
    (tmp_path / 'model.zip.partial').write_bytes(body[:4])
    monkeypatch.setattr(model.urllib.request, 'urlopen', lambda *a, **kw: Response(body))
    assert model.fetch_asset(record(body), tmp_path).read_bytes() == body


def test_model_digest_mismatch_does_not_publish_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(model.urllib.request, 'urlopen', lambda *a, **kw: Response(b'wrong'))
    with pytest.raises(RuntimeError, match='mismatch'):
        model.fetch_asset(record(b'right'), tmp_path)
    assert not (tmp_path / 'model.zip').exists()


def test_zip_path_traversal_is_rejected(tmp_path):
    archive = tmp_path / 'model.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('bge-m3/../outside.txt', b'x')
    manifest = {'files': [{'path': '../outside.txt', 'bytes': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}]}
    with pytest.raises(RuntimeError, match='Unsafe'):
        model.extract_release(archive, manifest, tmp_path / 'model')
    assert not (tmp_path / 'outside.txt').exists()


def test_zip_hash_failure_preserves_previous_component(tmp_path):
    destination = tmp_path / 'model'
    destination.mkdir()
    (destination / 'config.json').write_bytes(b'previous')
    archive = tmp_path / 'model.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr('bge-m3/config.json', b'wrong')
    manifest = {'files': [{'path': 'config.json', 'bytes': 5, 'sha256': hashlib.sha256(b'right').hexdigest()}]}
    with pytest.raises(RuntimeError, match='SHA256'):
        model.extract_release(archive, manifest, destination)
    assert (destination / 'config.json').read_bytes() == b'previous'


def test_storage_setup_preserves_existing_history_and_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, 'ROOT', tmp_path)
    for name in (
        'character/avatar.png',
        'character/stickers/10-red-pat.png',
        'assets/ye-shunguang/warm-dawn-full-body.webp',
        'voice/ye-shunguang/reference-original.mp3',
    ):
        path = tmp_path / 'source/resources' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    first = setup.application()
    from app.store import Store

    store = Store(tmp_path / first['database'])
    conversation = store.create_conversation()
    store.add_message(conversation['id'], 'user', 'A synthetic test message')
    settings = tmp_path / 'data/settings.json'
    settings.write_text('{"fixture":"preserve"}', encoding='utf-8')
    before = (tmp_path / first['database']).read_bytes()
    assert setup.application()['database_action'] == 'existing_database_preserved'
    assert (tmp_path / first['database']).read_bytes() == before
    assert settings.read_text() == '{"fixture":"preserve"}'


def test_receipt_records_failure_without_claiming_success(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    monkeypatch.setattr(installer, 'STATE', tmp_path / 'data/install')
    installer.write_receipt({'status': 'failed', 'stage': 'model_download', 'frontend': False})
    receipt = (tmp_path / 'data/install-list.md').read_text(encoding='utf-8')
    assert '**failed**' in receipt and 'model_download' in receipt
    assert json.loads((tmp_path / 'data/install/result.json').read_text())['status'] == 'failed'


def test_gpu_selection_requires_driver_and_memory(monkeypatch):
    monkeypatch.setattr(installer.shutil, 'which', lambda name: 'nvidia-smi')

    def fake_run(arguments, **kwargs):
        output = 'CUDA Version: 12.8' if len(arguments) == 1 else '4096\n'
        return subprocess.CompletedProcess(arguments, 0, stdout=output)

    monkeypatch.setattr(installer, 'run', fake_run)
    assert installer.gpu_candidate() is False


def test_existing_native_runtime_does_not_download(monkeypatch):
    monkeypatch.setattr(installer, 'vc_runtime_present', lambda: True)
    monkeypatch.setattr(installer.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('Unexpected download'))
    receipt = {}
    installer.ensure_vc_runtime(receipt)
    assert receipt['vc_runtime']['action'] == 'existing_system_runtime'


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Authenticode validation requires powershell.exe')
def test_unsigned_native_installer_is_rejected_before_execution(tmp_path):
    candidate = tmp_path / 'unsigned.exe'
    candidate.write_bytes(b'not an executable')
    result = subprocess.run(
        [
            'powershell.exe',
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            str(ROOT / 'scripts/install-vc-runtime.ps1'),
            '-InstallerPath',
            str(candidate),
        ],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert b'valid Microsoft signature' in result.stdout


def test_failed_cuda_execution_installs_cpu_and_leaves_skip_model_unverified(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    (tmp_path / '.venv-rag').mkdir()
    monkeypatch.setattr(installer, 'create_environment', lambda name: tmp_path / 'python.exe')
    monkeypatch.setattr(installer, 'gpu_candidate', lambda: True)
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append([str(a) for a in arguments])
        failed = any('torch.cuda.is_available' in str(a) for a in arguments)
        return subprocess.CompletedProcess(arguments, 1 if failed else 0, stdout='2.11.0+cu128\n')

    monkeypatch.setattr(installer, 'run', fake_run)
    receipt = {'pip_reports': []}
    installer.install_rag(SimpleNamespace(cpu=False, skip_model=True), receipt)
    assert receipt['cuda_fallback'] is True
    assert any('https://download.pytorch.org/whl/cpu' in call for call in calls)
    assert json.loads((tmp_path / '.venv-rag/rag-runtime.json').read_text())['verified'] is False


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows runtime probe')
def test_installer_can_probe_python_without_installing(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/install-project.py'), '--python-info'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info['version'][:2] == list(sys.version_info[:2])
    assert info['supported'] is True
    assert not (tmp_path / 'data').exists()


@pytest.mark.parametrize('minor', [11, 12, 13, 14])
def test_install_preflight_accepts_supported_python(minor, tmp_path, monkeypatch):
    version_type = type('Version', (tuple,), {'releaselevel': 'final'})
    with monkeypatch.context() as patch:
        patch.setattr(installer, 'ROOT', tmp_path)
        patch.setattr(installer, 'os', SimpleNamespace(name='nt'))
        patch.setattr(installer.sys, 'version_info', version_type((3, minor, 9)))
        patch.setattr(installer.platform, 'machine', lambda: 'AMD64')
        patch.setattr(installer.shutil, 'disk_usage', lambda _: SimpleNamespace(free=20 * 1024**3))
        installer.preflight(rag_only=True)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows installation entry points')
@pytest.mark.parametrize('entry', ['install.ps1', 'install-rag.ps1'])
def test_install_entry_accepts_explicit_python_without_installing(entry, installer_entry_scripts):
    result = subprocess.run(
        [
            'powershell.exe',
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            str(installer_entry_scripts / entry),
            '-PythonPath',
            sys.executable,
            '-CheckPython',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['version'][:2] == list(sys.version_info[:2])


@pytest.fixture
def installer_entry_scripts(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    for name in ['install.ps1', 'install-rag.ps1', 'select-python.ps1']:
        source = ROOT / 'scripts' / name
        if source.exists():
            shutil.copyfile(source, scripts / name)
    # A stub installer makes even an old entry point unable to touch the real project.
    (scripts / 'install-project.py').write_text(
        'import json,sys\n'
        'assert sys.argv[1:] == ["--python-info"], "Unexpected installation attempt"\n'
        'print(json.dumps({"supported":True,"version":list(sys.version_info[:3])}))\n',
        encoding='utf-8',
    )
    return scripts


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows installation entry points')
def test_install_entry_finds_python_on_path_without_launcher(installer_entry_scripts):
    environment = {**os.environ, 'PATH': str(Path(sys.executable).parent)}
    result = subprocess.run(
        [
            shutil.which('powershell.exe'),
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            str(installer_entry_scripts / 'install.ps1'),
            '-CheckPython',
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['version'][:2] == list(sys.version_info[:2])


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows installation entry points')
def test_unknown_install_option_is_rejected_before_launch(installer_entry_scripts):
    result = subprocess.run(
        [
            'powershell.exe',
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            str(installer_entry_scripts / 'install.ps1'),
            '-NotAnInstallOption',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert 'Unexpected installation attempt' not in result.stdout + result.stderr


def test_existing_environment_is_reused_on_supported_python(tmp_path, monkeypatch):
    python = tmp_path / '.venv/Scripts/python.exe'
    python.parent.mkdir(parents=True)
    python.touch()
    info = {'version': [3, 12, 9], 'supported': True}
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    monkeypatch.setattr(
        installer.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=json.dumps(info))
    )
    with monkeypatch.context() as patch:
        patch.setattr(installer.sys, 'version_info', (3, 12, 9))
        assert installer.create_environment('.venv') == python


def test_receipt_identifies_the_actual_python_without_machine_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    monkeypatch.setattr(installer, 'STATE', tmp_path / 'data/install')
    installer.write_receipt({'status': 'failed', 'stage': 'preflight', 'frontend': False})
    receipt = json.loads((tmp_path / 'data/install/result.json').read_text(encoding='utf-8'))
    assert receipt['python']['version'][:2] == list(sys.version_info[:2])
    assert 'executable' not in receipt['python']


def test_incomplete_existing_environment_fails_preflight_without_replacement(tmp_path, monkeypatch):
    environment = tmp_path / '.venv'
    environment.mkdir()
    marker = environment / 'preserve.txt'
    marker.write_text('keep this environment', encoding='utf-8')
    monkeypatch.setattr(installer, 'ROOT', tmp_path)
    monkeypatch.setattr(installer, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(installer.shutil, 'disk_usage', lambda _: SimpleNamespace(free=20 * 1024**3))
    with pytest.raises(RuntimeError, match='incomplete'):
        installer.preflight(rag_only=True)
    assert marker.read_text(encoding='utf-8') == 'keep this environment'
