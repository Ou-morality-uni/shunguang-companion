"""Server contracts: temporary data and no paid services or real QQ messages."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app import config, llm, main, runtime
from backend.app.store import Store


def test_server_installer_exposes_explicit_package_source_selection():
    entry = Path(__file__).resolve().parents[2] / 'deploy/server-lite/manage.py'
    result = subprocess.run(
        [sys.executable, str(entry), 'install', '--help'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    assert result.returncode == 0
    assert '--pip-source' in result.stdout
    assert 'official,tencent,aliyun' in result.stdout


def test_server_admin_initializes_web_only_without_qq_configuration(tmp_path):
    key = tmp_path / 'master.key'
    key.write_bytes(Fernet.generate_key())
    key.chmod(0o600)
    directory = tmp_path / 'data'
    result = subprocess.run(
        [sys.executable, '-m', 'backend.server_admin', 'init'],
        input=json.dumps({'password': 'offline-new-password'}),
        text=True,
        capture_output=True,
        encoding='utf-8',
        env={
            **os.environ,
            'SHUNGUANG_MODE': 'server',
            'SHUNGUANG_DATA_DIR': str(directory),
            'SHUNGUANG_MASTER_KEY_FILE': str(key),
            'PYTHONIOENCODING': 'utf-8',
        },
    )
    assert result.returncode == 0, result.stderr
    assert (directory / 'access.json').is_file()
    assert not (directory / 'qq').exists()


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setenv('SHUNGUANG_MODE', 'server')
    key = tmp_path / 'master.key'
    key.write_bytes(Fernet.generate_key())
    key.chmod(0o600)
    monkeypatch.setenv('SHUNGUANG_MASTER_KEY_FILE', str(key))
    monkeypatch.setattr(runtime, 'store', Store(tmp_path / 'companion.sqlite3'))
    with TestClient(main.app) as client:
        yield client, key


def test_server_reports_disabled_knowledge_without_vector_environment(server):
    client, _ = server
    capabilities = client.get('/api/capabilities').json()
    assert capabilities['deployment_mode'] == 'server'
    assert capabilities['local_knowledge'] is False
    status = client.get('/api/rag/status').json()
    assert status['enabled'] is False and status['ready'] is False
    for url, payload in [('/api/rag/rebuild', {}), ('/api/rag/search', {'query': '叶瞬光'})]:
        response = client.post(url, json=payload)
        assert response.status_code == 409
        assert '轻量模式' in response.json()['detail']
    assert client.get('/api/health').json()['status'] == 'ok'


def test_desktop_lite_keeps_desktop_credentials_and_disables_local_knowledge(tmp_path, monkeypatch):
    monkeypatch.setenv('SHUNGUANG_MODE', 'desktop')
    install = tmp_path / 'install'
    install.mkdir()
    (install / 'preferences.json').write_text('{"mode":"lite","qq":false}')
    client = TestClient(main.app)
    state = client.get('/api/capabilities').json()
    assert state['deployment_mode'] == 'desktop'
    assert state['local_knowledge'] is False
    assert client.post('/api/rag/rebuild').status_code == 409


def test_server_settings_are_encrypted_and_survive_reload(server):
    client, key = server
    response = client.patch(
        '/api/settings',
        json={
            'base_url': 'https://example.com/v1',
            'model': 'offline-test',
            'temperature': 0.7,
            'timeout': 45,
            'api_key': 'private-unit-key',
        },
    )
    assert response.status_code == 200
    assert config.load_config().llm_api_key.get_secret_value() == 'private-unit-key'
    saved = (config.DATA_DIR / 'settings.json').read_text(encoding='utf-8')
    assert 'private-unit-key' not in saved
    assert 'file:v1:' in saved
    key.unlink()
    with pytest.raises(RuntimeError):
        config.load_config()
    assert not key.exists()


def test_server_prompt_is_bounded_and_keeps_character_and_user_separate(monkeypatch):
    monkeypatch.setenv('SHUNGUANG_MODE', 'server')
    messages = llm.build_messages([{'role': 'user', 'status': 'complete', 'content': '你好'}])
    prompt = messages[0].content
    assert '服务器版角色补充' in prompt
    assert '不是用户的共同经历' in prompt
    assert len(prompt) < 16000


def test_server_data_directory_must_be_absolute(monkeypatch, tmp_path):
    monkeypatch.setenv('SHUNGUANG_DATA_DIR', 'relative/data')
    with pytest.raises(ValueError):
        config.data_directory()
    monkeypatch.setenv('SHUNGUANG_DATA_DIR', str(tmp_path))
    assert config.data_directory() == Path(tmp_path)


def test_search_budget_cache_and_scope_are_persistent(server, monkeypatch):
    from backend.app import tools

    client, _ = server
    response = client.patch(
        '/api/features',
        json={
            'tools': {
                'search_provider': 'tavily',
                'api_key': 'offline-search-key',
                'daily_limit': 2,
            }
        },
    )
    assert response.status_code == 200
    requests = []
    original = httpx.AsyncClient

    def upstream(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                'results': [
                    {
                        'title': 'Python',
                        'url': 'https://www.python.org/',
                        'content': 'Python official site',
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs)
    )
    args = {'query': 'Python', 'limit': 1}
    first = asyncio.run(tools.execute('web_search', args, scope='private-a'))
    assert first['ok'] and not first.get('cached')
    cached = asyncio.run(tools.execute('web_search', args, scope='private-a'))
    assert cached['cached'] and cached['fetched_at']
    other = asyncio.run(tools.execute('web_search', args, scope='group-b'))
    assert other['ok'] and not other.get('cached')
    exhausted = asyncio.run(tools.execute('web_search', {'query': 'different'}, scope='group-b'))
    assert exhausted['code'] == 'daily_limit'
    assert len(requests) == 2
    status = client.get('/api/features').json()['tools']
    assert status['usage']['used'] == 2 and status['daily_limit'] == 2


def test_search_page_reader_pins_public_ip_and_rejects_private_dns(monkeypatch):
    import socket

    from backend.app.web_pages import read_page

    seen = []
    original = httpx.AsyncClient

    def upstream(request):
        seen.append(request)
        assert request.url.host == '93.184.216.34'
        assert request.headers['host'] == 'public.example'
        assert 'authorization' not in request.headers
        return httpx.Response(
            200,
            headers={'content-type': 'text/html'},
            text='<html><script>bad()</script><main>Public page body</main></html>',
        )

    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs)
    )
    monkeypatch.setattr(
        socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
    )
    assert asyncio.run(read_page('https://public.example/page', 3)) == 'Public page body'
    monkeypatch.setattr(
        socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
    )
    with pytest.raises(ValueError):
        asyncio.run(read_page('https://private.example/page', 3))
    assert len(seen) == 1


def test_deployment_archive_rejects_traversal_and_preserves_existing_files(tmp_path):
    import importlib.util
    import zipfile

    script = Path(__file__).resolve().parents[2] / 'deploy/server-lite/manage.py'
    spec = importlib.util.spec_from_file_location('server_manage', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as out:
        out.writestr('ye-shunguang-server-lite/../../outside', 'bad')
    destination = tmp_path / 'new'
    destination.mkdir()
    existing = tmp_path / 'outside'
    existing.write_text('keep')
    with pytest.raises(ValueError):
        module.unpack(archive, destination)
    assert existing.read_text() == 'keep'


def test_encrypted_backup_restores_settings_and_authenticates_before_writing(server, tmp_path, monkeypatch):
    from cryptography.exceptions import InvalidTag

    from backend.server_admin import backup_archive, restore_archive

    client, key = server
    client.patch(
        '/api/settings',
        json={
            'base_url': 'https://example.com/v1',
            'model': 'offline',
            'temperature': 0.7,
            'timeout': 45,
            'api_key': 'backup-private-key',
        },
    )
    archive = tmp_path / 'backup.sgbackup'
    backup_archive(
        archive,
        'test-backup-password',
        [(config.DATA_DIR / 'settings.json', 'data/settings.json'), (key, 'secrets/master.key')],
        {'version': '0.7.0'},
    )
    assert b'backup-private-key' not in archive.read_bytes()
    destination = tmp_path / 'restored'
    destination.mkdir()
    with pytest.raises(InvalidTag):
        restore_archive(archive, destination, 'incorrect-password')
    assert not list(destination.iterdir())
    assert restore_archive(archive, destination, 'test-backup-password')['version'] == '0.7.0'
    monkeypatch.setattr(config, 'DATA_DIR', destination / 'data')
    monkeypatch.setenv('SHUNGUANG_MASTER_KEY_FILE', str(destination / 'secrets/master.key'))
    assert config.load_config().llm_api_key.get_secret_value() == 'backup-private-key'


def test_concurrent_searches_share_one_charge_and_failed_requests_count(server, monkeypatch):
    from backend.app import tools

    client, _ = server
    assert (
        client.patch(
            '/api/features',
            json={
                'tools': {
                    'search_provider': 'tavily',
                    'api_key': 'offline-key',
                    'daily_limit': 2,
                }
            },
        ).status_code
        == 200
    )
    calls = []
    original = httpx.AsyncClient

    async def upstream(request):
        calls.append(request)
        await asyncio.sleep(0.02)
        return httpx.Response(503)

    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs)
    )

    async def concurrent():
        return await asyncio.gather(*(tools.execute('web_search', {'query': 'same'}, scope='one') for _ in range(3)))

    results = asyncio.run(concurrent())
    assert all(result['code'] == 'upstream' for result in results)
    assert len(calls) == 1
    assert asyncio.run(tools.execute('web_search', {'query': 'again'}))['code'] == 'upstream'
    assert asyncio.run(tools.execute('web_search', {'query': 'third'}))['code'] == 'daily_limit'
    assert len(calls) == 2
