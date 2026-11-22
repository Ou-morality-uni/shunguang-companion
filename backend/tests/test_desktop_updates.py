import json
import os
import shutil
import socket
import sqlite3
import threading
import time
import venv
from pathlib import Path

import pytest

from backend.app.release_updates import select_release
from scripts import desktop_update as updater


def test_channel_uses_highest_ready_version_and_never_offers_a_downgrade():
    def release(version, preview=False, ready=True):
        return {
            'tag_name': 'v' + version,
            'prerelease': preview,
            'draft': False,
            'published_at': '2026-11-22T02:00:00Z',
            'body': '更新说明',
            'assets': [
                {
                    'name': f'shunguang-{version}-windows.zip',
                    'state': 'uploaded',
                    'size': 123,
                    'digest': 'sha256:' + 'a' * 64,
                }
            ]
            if ready
            else [],
        }

    releases = [release('0.7.14'), release('0.7.16', True), release('0.7.17', ready=False)]
    assert select_release(releases, 'stable', '0.7.13')['latest_version'] == '0.7.14'
    assert select_release(releases, 'preview', '0.7.13')['latest_version'] == '0.7.16'
    assert select_release(releases, 'stable', '0.7.16')['status'] == 'ahead'


# The fixture runs two actual Windows Python processes on the same localhost port.
SERVER = """
import json, sqlite3, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
root = Path.cwd()
version = json.loads((root / 'update.json').read_text())['version']
if version == '0.7.14' and (root / 'break-startup').exists():
    with sqlite3.connect(root / 'data/chat.sqlite3') as db:
        db.execute('DROP TABLE messages')
    (root / 'data/new-migration.db').touch()
    sys.exit(1)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        if self.path == '/api/health':
            self.wfile.write(json.dumps(dict(version=version, dependencies=dict(storage='ready'))).encode())
        else:
            self.wfile.write((root / 'frontend/dist/index.html').read_bytes())
with HTTPServer(('127.0.0.1', int(sys.argv[-1])), Handler) as server:
    server.timeout = 0.1
    (root / 'started').write_text(version)
    while not (root / 'stop').exists():
        server.handle_request()
        status = root / '.shunguang-update/status.json'
        if status.exists() and json.loads(status.read_text(encoding='utf-8'))['phase'] == 'draining':
            sys.exit(75)
"""


def wait_for(check):
    until = time.monotonic() + 30
    while time.monotonic() < until:
        if check():
            return
        time.sleep(0.1)
    pytest.fail('timed out waiting for desktop updater')


@pytest.mark.skipif(os.name != 'nt', reason='Windows desktop launcher')
@pytest.mark.parametrize('broken', [False, True])
def test_windows_restart_and_rollback(tmp_path, monkeypatch, broken):
    root = tmp_path / 'desktop'
    files = {
        'scripts/run-console.py': SERVER,
        'scripts/desktop_update.py': Path(updater.__file__).read_text(encoding='utf-8'),
        'scripts/prepare-launch.ps1': "function Get-InstallFingerprint { 'a' * 64 }",
        'backend/requirements.lock.txt': '',
        'update.json': '{"version":"0.7.13"}',
    }
    files[updater.LIST] = '\n'.join([*files, updater.LIST])
    files['frontend/dist/index.html'] = '<meta name="shunguang-version" content="0.7.13">'
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    candidate = tmp_path / 'new'
    shutil.copytree(root, candidate)
    for name in ['update.json', 'frontend/dist/index.html']:
        p = candidate / name
        p.write_text(files[name].replace('0.7.13', '0.7.14'), encoding='utf-8')
    package = tmp_path / 'release.zip'
    updater.build(candidate, package)
    monkeypatch.setattr(updater, 'download', lambda job, path: shutil.copyfile(package, path))
    venv.create(root / '.venv', with_pip=False)
    (root / 'data/install').mkdir(parents=True)
    (root / 'data/install/preferences.json').write_text('{}')
    with sqlite3.connect(root / 'data/chat.sqlite3') as db:
        db.execute('CREATE TABLE messages (content TEXT)')
        db.execute("INSERT INTO messages VALUES ('chat')")
    db.close()
    if broken:
        (root / 'break-startup').touch()
    updater.record_baseline(root)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    supervisor = threading.Thread(target=updater.supervise, args=(root, port), daemon=True)
    supervisor.start()
    try:
        wait_for(lambda: (root / 'started').is_file())
        updater.submit_request(root, '0.7.14', updater.sha(package), package.stat().st_size)
        status = root / updater.STATE / 'status.json'
        wait_for(lambda: updater.read_json(status, {}).get('phase') in {'failed', 'complete'})
        result = updater.read_json(status)
        assert result['phase'] == ('failed' if broken else 'complete'), result
        with sqlite3.connect(root / 'data/chat.sqlite3') as db:
            assert db.execute('SELECT content FROM messages').fetchall() == [('chat',)]
        db.close()
        assert not (root / 'data/new-migration.db').exists()
        expected = '0.7.13' if broken else '0.7.14'
        assert json.loads((root / 'update.json').read_text())['version'] == expected
        wait_for(lambda: (root / 'started').read_text() == expected)
    finally:
        (root / 'stop').touch()
        supervisor.join(10)
    assert not supervisor.is_alive()


def test_single_request_and_conflicting_local_edit(tmp_path):
    (tmp_path / updater.STATE).mkdir()
    first = updater.submit_request(tmp_path, '0.7.14', 'a' * 64, 42)
    with pytest.raises(FileExistsError):
        updater.submit_request(tmp_path, '0.7.14', 'a' * 64, 42)
    assert updater.read_json(tmp_path / updater.STATE / 'request.json')['id'] == first
    (tmp_path / 'README.md').write_text('my edits')
    with pytest.raises(ValueError, match='README'):
        updater.changes(tmp_path, {'README.md': 'before'}, {'README.md': 'after'})


def test_remote_client_cannot_request_release_install():
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app, base_url='http://192.168.0.5:8000') as client:
        result = client.post('/api/updates/install', json={'channel': 'stable', 'version': '0.7.14'})
        assert result.status_code == 403


def test_rejects_bad_sha_and_unavailable_release(tmp_path, monkeypatch):
    from io import BytesIO

    from fastapi import HTTPException

    response = BytesIO(b'abc')
    response.url = 'https://github.com/test'
    monkeypatch.setattr(updater, 'urlopen', lambda *args, **kwargs: response)
    with pytest.raises(ValueError, match='完整性'):
        updater.download({'version': '0.7.14', 'size': 3, 'digest': '0' * 64}, tmp_path / 'download')
    with pytest.raises(HTTPException) as failure:
        select_release([{'tag_name': 'v0.7.15', 'draft': True}], 'stable', '0.7.13')
    assert failure.value.status_code == 404
