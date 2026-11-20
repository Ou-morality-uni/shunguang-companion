from threading import Event
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.app import config, main, service_install


def test_install_knowledge_requires_local_confirmation_and_keeps_one_job(tmp_path, monkeypatch):
    entered = Event()
    finish = Event()
    monkeypatch.setattr(service_install, 'supported', lambda: True)
    monkeypatch.setattr(service_install, 'state', {'state': 'idle', 'stage': None, 'error': None})

    def install():
        entered.set()
        finish.wait(3)

    monkeypatch.setattr(service_install, 'run', install)
    with TestClient(main.app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000)) as client:
        endpoint = '/api/services/install/knowledge'
        headers = {'origin': 'http://127.0.0.1'}
        assert client.post(endpoint, json={'confirmed': True}).status_code == 403
        assert (
            client.post(endpoint, json={'confirmed': True}, headers={'origin': 'https://untrusted.test'}).status_code
            == 403
        )
        assert (
            client.post(
                endpoint, json={'confirmed': True}, headers={**headers, 'forwarded': 'for=127.0.0.1'}
            ).status_code
            == 403
        )
        assert client.post(endpoint, json={'confirmed': False}, headers=headers).status_code == 422
        assert not entered.is_set()
        try:
            first = client.post(endpoint, json={'confirmed': True}, headers=headers)
            assert first.status_code == 202
            assert entered.wait(3)
            second = client.post(endpoint, json={'confirmed': True}, headers=headers)
            assert second.json() == first.json()
            assert client.get('/api/services/install').json()['knowledge_install']['state'] == 'running'
        finally:
            finish.set()


def test_ready_knowledge_can_be_enabled_without_restarting(tmp_path, monkeypatch):
    preference = tmp_path / 'install/preferences.json'
    preference.parent.mkdir()
    preference.write_text('{"mode":"lite","qq":false}', encoding='utf-8')
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(service_install.rag, 'status', lambda: {'ready': True})
    monkeypatch.setattr(service_install, 'state', {'state': 'running', 'stage': None, 'error': None})
    assert not config.local_knowledge_enabled()
    service_install.run()
    assert config.local_knowledge_enabled()
    assert service_install.snapshot()['state'] == 'ready'


def test_failed_model_download_does_not_enable_retrieval(tmp_path, monkeypatch):
    preference = tmp_path / 'install/preferences.json'
    preference.parent.mkdir()
    original = '{"mode":"lite","qq":true}'
    preference.write_text(original, encoding='utf-8')
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(service_install.rag, 'status', lambda: {'ready': False})
    monkeypatch.setattr(service_install, 'state', {'state': 'running', 'stage': None, 'error': None})
    child = MagicMock()
    child.__enter__.return_value = child
    child.stdout = ['RAG_STAGE: model_download\n', 'RAG_FAILED: model_download\n']
    child.wait.return_value = 1
    monkeypatch.setattr(service_install.subprocess, 'Popen', lambda *args, **kwargs: child)
    monkeypatch.setattr(service_install.subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
    service_install.run()
    assert not config.local_knowledge_enabled()
    assert preference.read_text(encoding='utf-8') == original
    assert '下载或完整性校验失败' in service_install.snapshot()['error']
