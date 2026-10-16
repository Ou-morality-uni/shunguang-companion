import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from backend.app import config, credentials, main, runtime, tools
from backend.app.logging_setup import report_error
from backend.app.migrations import LEGACY_SCHEMA, SCHEMA_VERSION
from backend.app.routes import chat
from backend.app.routes import settings as settings_routes
from backend.app.store import Store


def test_connection_check_rejects_empty_model_text(client, monkeypatch):
    config.save_config(config.ModelConfig(llm_model='test', llm_api_key='test-key'))

    class Model:
        async def ainvoke(self, _):
            return AIMessageChunk(content='')

    monkeypatch.setattr(settings_routes, 'build_model', lambda _: Model())
    response = client.post('/api/providers/test')
    assert response.status_code == 502
    assert '没有返回文本' in response.json()['detail']


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'store', Store(tmp_path / 'test.db'))
    runtime.busy.clear()
    runtime.stops.clear()
    runtime.finished.clear()
    monkeypatch.setattr(tools, 'schemas', lambda _: [])
    with TestClient(main.app) as client:
        yield client


def test_lazy_creation_and_invalid_config_leave_no_conversation(client, monkeypatch):
    assert client.post('/api/chat', json={'content': '你好'}).status_code == 503
    assert client.get('/api/conversations').json() == []
    config.save_config(config.ModelConfig(llm_model='test', llm_api_key='test-only'))

    class Model:
        async def astream(self, history):
            yield AIMessageChunk(content='你好')

    monkeypatch.setattr(chat, 'build_model', lambda _: Model())
    response = client.post('/api/chat', json={'content': '首次对话'})
    assert response.status_code == 200
    frame = json.loads(response.text.split('data: ', 1)[1].split('\n\n')[0])
    cid = frame['conversation_id']
    assert client.get('/api/conversations').json()[0]['id'] == cid
    assert len(runtime.store.messages(cid)) == 2


def test_delete_detaches_confirmed_memory_and_removes_candidates(client):
    cid = runtime.store.create_conversation()['id']
    message = runtime.store.add_message(cid, 'user', '我喜欢茶')
    candidate = runtime.store.add_candidates(
        cid, [{'key': '喜好', 'value': '茶', 'evidence': '我喜欢茶', 'source_message_id': message['id']}]
    )[0]
    runtime.store.confirm_candidates([{'id': candidate['id'], 'key': '喜好', 'value': '茶'}])
    runtime.busy.add(cid)
    assert client.delete(f'/api/conversations/{cid}').status_code == 409
    assert len(runtime.store.messages(cid)) == 1
    runtime.busy.clear()
    assert client.delete(f'/api/conversations/{cid}').status_code == 204
    assert client.get(f'/api/conversations/{cid}/messages').status_code == 404
    assert runtime.store.list_memories()[0]['source_message_id'] is None
    with runtime.store.connect() as db:
        assert db.execute('SELECT count(*) FROM memory_candidates').fetchone()[0] == 0
    with pytest.raises(ValueError):
        runtime.store.add_candidates(cid, [candidate])


def test_legacy_migration_backs_up_and_keeps_order_metadata_and_memory(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY_SCHEMA)
        db.execute("INSERT INTO conversations VALUES ('c','title','now','now')")
        for mid in ('z', 'a', 'm'):
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (mid, 'c', 'user', mid, 'complete', 'now'))
        db.execute("INSERT INTO memories VALUES ('fact','key','value','z','now','now')")
    store = Store(path)
    store.initialize()
    store.initialize()
    assert [row['id'] for row in store.messages('c')] == ['z', 'a', 'm']
    assert [row['id'] for row in store.messages('c', 1, 3)] == ['a']
    assert store.list_memories()[0]['value'] == 'value'
    with store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1


def test_future_schema_is_rejected_without_downgrade(tmp_path):
    store = Store(tmp_path / 'future.db')
    with store.connect() as db:
        db.execute('PRAGMA user_version=999')
    with pytest.raises(RuntimeError):
        store.initialize()
    with store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 999


def test_health_contract_and_private_logging(client, monkeypatch):
    assert set(client.get('/api/health').json()) == {'status', 'version'}
    captured = []
    from backend.app import logging_setup

    monkeypatch.setattr(logging_setup.logger, 'warning', lambda *args: captured.append(args))
    report_error('chat', RuntimeError('Bearer user-secret and private conversation'))
    assert 'user-secret' not in str(captured) and 'private conversation' not in str(captured)
    assert 'MessageOut' in client.get('/openapi.json').json()['components']['schemas']


def test_keyring_envelope_and_legacy_dpapi(monkeypatch):
    class Vault:
        saved = {}

        def get_password(self, service, key):
            return self.saved.get(key)

        def set_password(self, service, key, secret):
            self.saved[key] = secret

    vault = Vault()
    monkeypatch.setattr(credentials.KeyringBackend, 'vault', lambda _: vault)
    reference = credentials.KeyringBackend().encrypt('test-only')
    assert credentials.decrypt_secret('keyring:v1:' + reference) == 'test-only'
    monkeypatch.setattr(credentials.WindowsDpapiBackend, 'decrypt', lambda _, encoded: 'legacy-' + encoded)
    assert credentials.decrypt_secret('old') == 'legacy-old'
    assert credentials.decrypt_secret('dpapi:v1:old') == 'legacy-old'


def test_empty_response_has_specific_message(client, monkeypatch):
    config.save_config(config.ModelConfig(llm_model='test', llm_api_key='test-only'))

    class EmptyModel:
        async def astream(self, history):
            yield AIMessageChunk(content='')

    monkeypatch.setattr(chat, 'build_model', lambda _: EmptyModel())
    result = client.post('/api/chat', json={'content': '你好'})
    assert '没有返回文本' in result.text
    assert '无法连接模型' not in result.text


def test_prompt_and_tracing_privacy():
    import os

    from backend.app.llm import build_messages

    assert os.environ['LANGSMITH_TRACING'] == 'false'
    prompt = build_messages([])[0].content
    assert 'AI' in prompt and '不能虚构数据' in prompt


def test_simultaneous_turns_and_delete_are_serialized(client, monkeypatch):
    config.save_config(config.ModelConfig(llm_model='test', llm_api_key='test-only'))

    class Model:
        async def astream(self, history):
            yield AIMessageChunk(content='ok')

    monkeypatch.setattr(chat, 'build_model', lambda _: Model())
    cid = runtime.store.create_conversation()['id']

    async def run():
        payload = chat.ChatRequest(conversation_id=cid, content='test')
        results = await asyncio.gather(chat.chat(payload), chat.chat(payload), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(failures) == 1 and failures[0].status_code == 409
        with pytest.raises(Exception) as failure:
            await chat.delete_conversation(cid)
        assert failure.value.status_code == 409
        response = next(r for r in results if not isinstance(r, Exception))
        async for _ in response.body_iterator:
            pass
        assert cid not in runtime.busy

    asyncio.run(run())


def test_stop_during_tool_wait_commits_before_acknowledging(client, monkeypatch):
    config.save_config(config.ModelConfig(llm_model='test', llm_api_key='test-only'))
    monkeypatch.setattr(tools, 'schemas', lambda _: [{'name': 'weather'}])

    class Model:
        def bind_tools(self, schemas):
            return self

        async def astream(self, history):
            yield AIMessageChunk(content='', tool_calls=[{'name': 'weather', 'id': 't', 'args': {}}])

    monkeypatch.setattr(chat, 'build_model', lambda _: Model())

    async def run():
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def slow_tool(name, args):
            entered.set()
            try:
                await asyncio.sleep(30)
            finally:
                cancelled.set()

        monkeypatch.setattr(tools, 'execute', slow_tool)
        response = await chat.chat(chat.ChatRequest(content='天气'))
        iterator = response.body_iterator
        first = await anext(iterator)
        cid = json.loads(first.split('data: ')[1])['conversation_id']

        async def drain():
            return [frame async for frame in iterator]

        draining = asyncio.create_task(drain())
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert await asyncio.wait_for(chat.stop_chat(cid), timeout=2) == {'ok': True}
        assert cancelled.is_set()
        assert runtime.store.messages(cid)[-1]['status'] == 'interrupted'
        assert 'interrupted' in ''.join(await draining)

    asyncio.run(run())


def test_failed_migration_rolls_back_every_schema_change(tmp_path):
    from backend.app.migrations import migrate

    store = Store(tmp_path / 'rollback.db')
    with store.connect() as db:
        db.executescript(LEGACY_SCHEMA)
        db.execute("INSERT INTO conversations VALUES ('c','title','now','now')")
        db.execute("INSERT INTO messages VALUES ('m','c','user','kept','complete','now')")

    class FailingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement):
            if statement.startswith('DROP TABLE messages_legacy'):
                raise sqlite3.OperationalError('simulated migration failure')
            return self.connection.execute(statement)

    with pytest.raises(sqlite3.OperationalError):
        with store.connect() as db:
            migrate(FailingConnection(db))
    with store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0
        assert db.execute('SELECT content FROM messages').fetchone()[0] == 'kept'
        assert 'seq' not in {row['name'] for row in db.execute('PRAGMA table_info(messages)')}
