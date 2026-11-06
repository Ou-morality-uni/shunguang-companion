"""Run inside the server image: real Linux dependencies, synthetic data/providers."""

import importlib.util
import json
import os
import resource
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet


def main():
    from backend.app.constants import VERSION

    for name in ('torch', 'transformers', 'qdrant_client'):
        assert importlib.util.find_spec(name) is None, name
    with tempfile.TemporaryDirectory(prefix='server-verify-') as temporary:
        root = Path(temporary)
        key = root / 'master.key'
        key.write_bytes(Fernet.generate_key())
        key.chmod(0o600)
        os.environ.update(
            SHUNGUANG_MODE='server',
            SHUNGUANG_DATA_DIR=str(root / 'data'),
            SHUNGUANG_MASTER_KEY_FILE=str(key),
            SHUNGUANG_LAN_MODE='1',
        )
        from fastapi.testclient import TestClient
        from langchain_core.messages import AIMessageChunk

        from backend.app import config
        from backend.app import main as application
        from backend.server_admin import backup_archive, restore_archive

        config.DATA_DIR.mkdir()
        initialized = subprocess.run(
            [sys.executable, '-m', 'backend.server_admin', 'init'],
            input=json.dumps(
                {'password': 'offline-admin-password', 'bot_id': '10001', 'token': 'synthetic-onebot-token'}
            ),
            text=True,
            capture_output=True,
        )
        assert initialized.returncode == 0, initialized.stderr
        from backend.app.qq.repository import QQRepository

        repository = QQRepository(config.DATA_DIR / 'qq')
        connection = repository.connection(secret=True)
        assert connection.token == 'synthetic-onebot-token'
        connection.enabled = False
        repository.save_connection(connection)

        class Model:
            async def astream(self, messages):
                assert '服务器版角色补充' in messages[0].content
                yield AIMessageChunk(content='\n\n容器里的小光准备好啦。')

        with (
            patch('backend.app.routes.chat.build_model', return_value=Model()),
            patch('backend.app.memory_jobs.build_memory_model', side_effect=RuntimeError('offline')),
        ):
            with TestClient(application.app) as client:
                assert client.get('/api/health').json() == {'status': 'ok', 'version': VERSION}
                assert client.get('/api/features').status_code == 401
                assert client.post('/api/auth/login', json={'password': 'offline-admin-password'}).status_code == 200
                assert client.get('/api/capabilities').json()['local_knowledge'] is False
                assert client.get('/api/features').json()['tts']['reference_sha256']
                assert client.get('/api/rag/status').json()['enabled'] is False
                assert client.post('/api/rag/rebuild').status_code == 409
                assert (
                    client.patch(
                        '/api/settings',
                        json={
                            'base_url': 'https://example.invalid/v1',
                            'model': 'offline-test',
                            'api_key': 'synthetic-model-key',
                            'temperature': 0.7,
                            'timeout': 5,
                        },
                    ).status_code
                    == 200
                )
                assert client.get('/api/settings').json()['has_api_key']
                cid = client.post('/api/conversations').json()['id']
                chat = client.post('/api/chat', json={'conversation_id': cid, 'content': '你好'})
                assert 'event: done' in chat.text
                messages = client.get(f'/api/conversations/{cid}/messages').json()
                assert messages[-1]['content'].startswith('容器里的小光')
                assert client.get('/api/resources/character/avatar.png').status_code == 200
                assert client.get('/api/qq/state').json()['status'] == 'disabled'
            with TestClient(application.app) as restarted:
                assert restarted.post('/api/auth/login', json={'password': 'offline-admin-password'}).status_code == 200
                assert restarted.get('/api/settings').json()['has_api_key']
                assert len(restarted.get(f'/api/conversations/{cid}/messages').json()) == 2
        output = root / 'backup.sgbackup'
        backup_archive(
            output,
            'offline-backup-password',
            [(config.DATA_DIR, 'data'), (key, 'secrets/master.key')],
            {'version': VERSION},
        )
        restored = root / 'restore'
        restored.mkdir()
        assert restore_archive(output, restored, 'offline-backup-password')['version'] == VERSION
        config.DATA_DIR = restored / 'data'
        os.environ['SHUNGUANG_MASTER_KEY_FILE'] = str(restored / 'secrets/master.key')
        assert config.load_config().llm_api_key.get_secret_value() == 'synthetic-model-key'
    print(
        json.dumps(
            {
                'linux_container': 'passed',
                'network': 'disabled',
                'memory_limit_mb': 512,
                'process_peak_rss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                'real_qq': False,
                'real_model_api': False,
                'build': json.loads(Path('/app/server-build.json').read_text()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == '__main__':
    main()
