"""Public boundary regressions for the quality upgrade."""

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessageChunk

from backend.app.access import allowed_hosts as resolve_allowed_hosts
from backend.app.routes.chat import cancellable_chunks, tool_content
from backend.app.store import Store


def test_large_tool_result_with_null_task_retains_preview():
    result = json.loads(tool_content({'ok': False, 'task': None, 'detail': '长' * 17000}))
    assert result['truncated'] is True
    assert result['task_id'] is None
    assert result['preview']


def test_legacy_null_task_fields_remain_readable_and_do_not_block_deletion(tmp_path):
    from backend.app.conversation_cleanup import delete
    from backend.app.filework import FileWork

    store = Store(tmp_path / 'chat.sqlite3')
    store.initialize()
    workspace = store.grant_workspace(str(tmp_path), 'synthetic')
    task = store.create_file_task(workspace['id'], 'legacy', [], 'complete')
    with store.connect() as db:
        db.execute("UPDATE file_tasks SET steps='null',context='null' WHERE id=?", (task['id'],))
    saved = store.get_file_task(task['id'])
    assert saved['steps'] == []
    assert saved['context'] == {}
    assert store.list_file_tasks()[0]['context'] == {}
    cid = store.create_conversation()['id']
    work = FileWork(store)
    try:
        assert delete(work, cid)
        assert store.get_file_task(task['id']) is not None
    finally:
        work.close()


def test_text_checkpoint_preserves_saved_tool_metadata(tmp_path):
    store = Store(tmp_path / 'chat.sqlite3')
    store.initialize()
    conversation = store.create_conversation()['id']
    tools = [{'id': 'tool-1', 'status': 'complete'}]
    message = store.add_message(conversation, 'assistant', '', 'streaming', {'tools': tools})
    store.update_message(message['id'], 'partial', 'streaming')
    saved = store.messages(conversation)[0]
    assert saved['content'] == 'partial'
    assert saved['tools'] == tools


def test_model_connection_failure_before_output_can_recover():
    class Model:
        attempts = 0

        async def astream(self, history):
            self.attempts += 1
            if self.attempts == 1:
                raise httpx.ConnectError('synthetic disconnect')
            yield AIMessageChunk(content='recovered')

    async def run():
        return [chunk.content async for chunk in cancellable_chunks(Model(), [], asyncio.Event())]

    assert asyncio.run(run()) == ['recovered']


def test_model_failure_after_output_is_not_replayed():
    class Model:
        async def astream(self, history):
            yield AIMessageChunk(content='partial')
            raise httpx.ReadError('synthetic disconnect')

    async def run():
        received = []
        with pytest.raises(httpx.ReadError):
            async for chunk in cancellable_chunks(Model(), [], asyncio.Event()):
                received.append(chunk.content)
        return received

    assert asyncio.run(run()) == ['partial']


def test_host_cache_reuses_dns_but_updates_environment_allowlist(monkeypatch):
    from backend.app import access

    monkeypatch.setattr(access, '_host_expires', 0.0)
    monkeypatch.setattr(access, '_host_addresses', set())
    addresses = iter(['192.0.2.1', '192.0.2.2'])
    monkeypatch.setattr(access.socket, 'getaddrinfo', lambda *args: [(None, None, None, None, (next(addresses), 0))])
    monkeypatch.setenv('SHUNGUANG_ALLOWED_HOSTS', 'first.example')
    assert 'first.example' in resolve_allowed_hosts()
    monkeypatch.setenv('SHUNGUANG_ALLOWED_HOSTS', 'second.example')
    hosts = resolve_allowed_hosts()
    assert '192.0.2.1' in hosts
    assert 'second.example' in hosts
    assert 'first.example' not in hosts


@pytest.mark.parametrize(('mode', 'expected'), [('desktop', 403), ('server', 200)])
def test_remote_settings_write_obeys_deployment_boundary(monkeypatch, mode, expected):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.routes import settings

    monkeypatch.setenv('SHUNGUANG_MODE', mode)
    app = FastAPI()
    app.include_router(settings.router)
    with TestClient(app, client=('192.0.2.10', 5000)) as client:
        response = client.patch(
            '/api/settings',
            json={
                'base_url': 'https://example.com/v1',
                'model': 'synthetic',
                'temperature': 0.7,
                'timeout': 30,
            },
        )
    assert response.status_code == expected


def test_corrupt_settings_are_preserved_and_can_be_reconfigured(tmp_path):
    from backend.app import config

    path = tmp_path / 'settings.json'
    path.write_text('{broken', encoding='utf-8')
    assert config.load_config().llm_model == ''
    assert config.saved_profiles() == []
    assert next(tmp_path.glob('settings.json.corrupt-*')).read_text(encoding='utf-8') == '{broken'
    config.save_config(config.ModelConfig(llm_model='recovered'))
    assert config.load_config().llm_model == 'recovered'


def test_corrupt_access_configuration_never_authenticates(tmp_path):
    from backend.app import access

    (tmp_path / 'access.json').write_text('{invalid', encoding='utf-8')
    assert access.check_password('anything') is False
    assert list(tmp_path.glob('access.json.corrupt-*'))


def test_invalid_password_hash_is_rejected_without_internal_error(tmp_path):
    from backend.app import access

    (tmp_path / 'access.json').write_text(json.dumps({'salt': 'ab' * 16, 'hash': '汉' * 64}), encoding='utf-8')
    assert access.check_password('anything') is False


def test_invalid_saved_profile_is_preserved_for_reconfiguration(tmp_path):
    from backend.app import config

    (tmp_path / 'settings.json').write_text('{"profiles":[{}]}', encoding='utf-8')
    assert config.saved_profiles() == []
    assert list(tmp_path.glob('settings.json.corrupt-*'))


@pytest.mark.parametrize(('mode', 'expected'), [('desktop', 403), ('server', 200)])
def test_remote_saved_connection_activation_obeys_admin_boundary(monkeypatch, mode, expected):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app import config
    from backend.app.routes import settings

    monkeypatch.setenv('SHUNGUANG_MODE', mode)
    config.save_config(config.ModelConfig(llm_base_url='https://example.com/v1', llm_model='synthetic'))
    app = FastAPI()
    app.include_router(settings.router)
    with TestClient(app, client=('192.0.2.10', 4000)) as client:
        response = client.post(
            '/api/providers/activate', json={'id': config.profile_id('https://example.com/v1', 'openai')}
        )
    assert response.status_code == expected


def test_error_diagnostics_include_safe_stack_and_request_id(monkeypatch):
    from backend.app import logging_setup

    captured = []
    monkeypatch.setattr(logging_setup.logger, 'warning', lambda value: captured.append(json.loads(value)))
    try:
        raise RuntimeError('private secret content')
    except RuntimeError as error:
        logging_setup.report_error('synthetic', error)
    assert captured[0]['error_type'] == 'RuntimeError'
    assert captured[0]['stack']
    assert 'private secret content' not in json.dumps(captured)


def test_automatic_migration_backups_have_bounded_retention(tmp_path):
    store = Store(tmp_path / 'chat.sqlite3')
    store.initialize()
    manual = tmp_path / 'backups' / 'manual.sqlite3'
    manual.parent.mkdir(exist_ok=True)
    manual.write_bytes(b'user-managed backup')
    for _ in range(7):
        with store.connect() as db:
            db.execute('DROP TABLE annotations')
            db.execute('PRAGMA user_version=8')
        store.initialize()
    assert len(list(manual.parent.glob('chat-v*.sqlite3'))) == 5
    assert manual.read_bytes() == b'user-managed backup'
