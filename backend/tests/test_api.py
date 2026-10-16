import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from backend.app import config, main, runtime
from backend.app.routes import chat as chat_routes
from backend.app.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(runtime, 'store', Store(tmp_path / 'test.sqlite3'))
    runtime.busy.clear()
    runtime.stops.clear()
    # Model doubles in these tests cover transport/history, with real tool tests separate.
    from backend.app import tools

    monkeypatch.setattr(tools, 'schemas', lambda _: [])
    with TestClient(main.app) as test_client:
        yield test_client


def conversation(client):
    response = client.post('/api/conversations')
    assert response.status_code == 201
    return response.json()['id']


def enable_model(monkeypatch):
    config.save_config(
        config.ModelConfig(
            llm_base_url='https://example.com/v1', llm_api_key='unit-test-secret', llm_model='unit-test-model'
        )
    )


def frames(response):
    return [json.loads(frame.split('data: ', 1)[1]) for frame in response.text.strip().split('\n\n')]


def test_new_user_has_no_seeded_conversations(client):
    assert client.get('/api/conversations').json() == []
    config = client.get('/api/settings').json()
    assert config['configured'] is False
    assert 'api_key' not in config and 'llm_api_key' not in config


def test_missing_key_blocks_chat_without_storing_turn(client):
    cid = conversation(client)
    result = client.post('/api/chat', json={'conversation_id': cid, 'content': '你好'})
    assert result.status_code == 503
    assert client.get(f'/api/conversations/{cid}/messages').json() == []


def test_settings_persist_without_secret(client, monkeypatch):
    enable_model(monkeypatch)
    payload = {'base_url': 'https://example.com/v1', 'model': 'test', 'temperature': 0.5, 'timeout': 30}
    assert client.patch('/api/settings', json=payload).status_code == 200
    assert client.get('/api/settings').json()['model'] == 'test'
    text = (config.DATA_DIR / 'settings.json').read_text()
    assert 'unit-test-secret' not in text and 'api_key_encrypted' in text
    payload['base_url'] = 'https://username:password@example.com/v1'
    assert client.patch('/api/settings', json=payload).status_code == 422


def test_unknown_conversation_and_blank_input(client):
    assert client.get('/api/conversations/unknown/messages').status_code == 404
    cid = conversation(client)
    assert client.post('/api/chat', json={'conversation_id': cid, 'content': '   '}).status_code == 422


def test_stream_persists_and_reuses_history(client, monkeypatch):
    enable_model(monkeypatch)
    received = []

    class FakeModel:
        async def astream(self, history):
            received.append(history)
            yield AIMessageChunk(content='你好，')
            yield AIMessageChunk(content='很高兴见到你。')

    monkeypatch.setattr(chat_routes, 'build_model', lambda _: FakeModel())
    cid = conversation(client)
    response = client.post('/api/chat', json={'conversation_id': cid, 'content': '你好'})
    assert response.status_code == 200
    assert 'event: done' in response.text
    assert frames(response)[-1]['content'] == '你好，很高兴见到你。'
    records = client.get(f'/api/conversations/{cid}/messages').json()
    assert [m['role'] for m in records] == ['user', 'assistant']
    assert client.get('/api/conversations').json()[0]['title'] == '你好'
    response = client.post('/api/chat', json={'conversation_id': cid, 'content': '再聊一句'})
    assert [m.content for m in received[-1] if m.type != 'system'] == ['你好', '你好，很高兴见到你。', '再聊一句']
    assert cid not in runtime.busy


def test_stream_failure_is_visible_sanitized_and_retryable(client, monkeypatch):
    enable_model(monkeypatch)

    class FailingModel:
        async def astream(self, history):
            yield AIMessageChunk(content='开始回复')
            raise RuntimeError('unit-test-secret should never be exposed')

    monkeypatch.setattr(chat_routes, 'build_model', lambda _: FailingModel())
    cid = conversation(client)
    response = client.post('/api/chat', json={'conversation_id': cid, 'content': '你好'})
    assert 'event: error' in response.text
    assert 'unit-test-secret' not in response.text
    records = client.get(f'/api/conversations/{cid}/messages').json()
    assert records[-1]['status'] == 'error'
    assert records[-1]['content'] == '开始回复'
    assert records[-1]['sticker'] is None
    assert cid not in runtime.busy


def test_parallel_turn_is_rejected(client, monkeypatch):
    enable_model(monkeypatch)
    cid = conversation(client)
    runtime.busy.add(cid)
    assert client.post('/api/chat', json={'conversation_id': cid, 'content': '你好'}).status_code == 409
    assert client.get(f'/api/conversations/{cid}/messages').json() == []


def test_store_reopen_keeps_history(client):
    cid = conversation(client)
    runtime.store.add_message(cid, 'user', '本机持久化验证')
    reopened = Store(runtime.store.path)
    reopened.initialize()
    assert reopened.messages(cid)[0]['content'] == '本机持久化验证'


def test_stream_closed_early_records_interruption(client, monkeypatch):
    enable_model(monkeypatch)

    class SlowModel:
        async def astream(self, history):
            yield AIMessageChunk(content='部分回复')
            await asyncio.sleep(60)

    monkeypatch.setattr(chat_routes, 'build_model', lambda _: SlowModel())
    cid = conversation(client)

    async def run():
        response = await chat_routes.chat(chat_routes.ChatRequest(conversation_id=cid, content='测试停止'))
        iterator = response.body_iterator
        await anext(iterator)  # accepted user
        await anext(iterator)  # first delta
        await iterator.aclose()

    asyncio.run(run())
    assert runtime.store.messages(cid)[-1]['status'] == 'interrupted'
    assert runtime.store.messages(cid)[-1]['content'] == '部分回复'
    assert runtime.store.messages(cid)[-1]['sticker'] is None
    assert cid not in runtime.busy


@pytest.mark.parametrize('hint,scene', [('comfort', 'comfort'), ('unknown_scene', 'neutral'), ('', 'neutral')])
def test_each_completed_reply_gets_one_persistent_sticker_without_spoken_controls(client, monkeypatch, hint, scene):
    enable_model(monkeypatch)
    calls = []

    class Model:
        async def astream(self, history):
            calls.append(history)
            assert any('[[sticker:' in message.content for message in history if message.type == 'system')
            raw = '我在，慢慢说。' + (f'[[sticker:{hint}]]' if hint else '')
            for char in raw:
                yield AIMessageChunk(content=char)

    monkeypatch.setattr(chat_routes, 'build_model', lambda _: Model())
    cid = conversation(client)
    previous = None
    for _ in range(2):
        response = client.post('/api/chat', json={'conversation_id': cid, 'content': '今天有点难过，想和你说说'})
        assert '[[sticker:' not in response.text
        complete = frames(response)[-1]
        assert complete['status'] == 'complete' and complete['content'] == '我在，慢慢说。'
        assert complete['sticker']['scene'] == scene and complete['sticker']['persona'] == 'red'
        assert complete['sticker']['id'] != previous
        previous = complete['sticker']['id']
        reloaded = client.get(f'/api/conversations/{cid}/messages').json()[-1]
        assert reloaded['sticker'] == complete['sticker']
        reopened = Store(runtime.store.path)
        reopened.initialize()
        assert reopened.messages(cid)[-1]['sticker'] == complete['sticker']
    assert len(calls) == 2  # No second model request just to select a sticker.


def test_tool_round_sticker_control_is_hidden_and_final_reply_controls_the_scene(client, monkeypatch):
    from backend.app import tools

    enable_model(monkeypatch)
    monkeypatch.setattr(tools, 'schemas', lambda _: [{'name': 'weather'}])

    async def execute(*args):
        return {'ok': False, 'error': 'test-only unavailable'}

    class Model:
        def bind_tools(self, schemas):
            return self

        async def astream(self, history):
            if history[-1].type == 'tool':
                assert history[-2].content == '先看看。'
                yield AIMessageChunk(content='没查到，我陪你聊会儿。[[sticker:comfort]]')
            else:
                yield AIMessageChunk(
                    content='先看看。[[sticker:thinking]]',
                    tool_calls=[{'name': 'weather', 'id': 'check', 'args': {'city': '长春'}}],
                )

    monkeypatch.setattr(tools, 'execute', execute)
    monkeypatch.setattr(chat_routes, 'build_model', lambda _: Model())
    response = client.post('/api/chat', json={'content': '今天有点难过，长春天气怎么样'})
    assert '[[sticker:' not in response.text
    result = frames(response)[-1]
    assert result['sticker']['scene'] == 'comfort'
    assert result['content'] == '先看看。没查到，我陪你聊会儿。'


def test_langchain_model_constructs_without_network(client, monkeypatch):
    from backend.app.llm import build_model

    enable_model(monkeypatch)
    model = build_model(config.load_config())
    assert model.model_name == 'unit-test-model'


def test_model_settings_ignore_environment(client, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'environment-secret-must-be-ignored')
    monkeypatch.setenv('LLM_MODEL', 'environment-model')
    result = client.get('/api/settings').json()
    assert result['has_api_key'] is False and result['model'] == ''


def test_ui_key_save_keep_replace_and_clear(client):
    payload = {
        'base_url': 'https://example.com/v1',
        'model': 'test',
        'temperature': 0.5,
        'timeout': 30,
        'api_key': 'first-test-secret',
    }
    response = client.patch('/api/settings', json=payload)
    assert response.status_code == 200 and response.json()['configured']
    assert 'first-test-secret' not in response.text
    assert config.load_config().llm_api_key.get_secret_value() == 'first-test-secret'
    text = (config.DATA_DIR / 'settings.json').read_text()
    assert 'first-test-secret' not in text
    payload.pop('api_key')
    payload['model'] = 'new-model'
    assert client.patch('/api/settings', json=payload).status_code == 200
    assert config.load_config().llm_api_key.get_secret_value() == 'first-test-secret'
    payload['api_key'] = ''
    assert client.patch('/api/settings', json=payload).json()['has_api_key']
    payload['api_key'] = 'replacement-test-secret'
    assert client.patch('/api/settings', json=payload).status_code == 200
    assert config.load_config().llm_api_key.get_secret_value() == 'replacement-test-secret'
    payload.pop('api_key')
    payload['clear_api_key'] = True
    assert not client.patch('/api/settings', json=payload).json()['has_api_key']
    assert 'api_key_encrypted' not in (config.DATA_DIR / 'settings.json').read_text()


def test_validation_does_not_echo_credentials(client):
    payload = {
        'base_url': 'https://example.com',
        'model': 'test',
        'temperature': 'bad-type',
        'timeout': 30,
        'api_key': 'never-echo-this-secret',
    }
    response = client.patch('/api/settings', json=payload)
    assert response.status_code == 422
    assert 'never-echo-this-secret' not in response.text


def test_key_in_model_field_is_rejected_without_echo(client):
    payload = {
        'base_url': 'https://example.com',
        'model': 'sk-test-secret-in-wrong-field',
        'temperature': 0.5,
        'timeout': 30,
    }
    response = client.patch('/api/settings', json=payload)
    assert response.status_code == 422
    assert 'sk-test-secret-in-wrong-field' not in response.text
    assert not (config.DATA_DIR / 'settings.json').exists()


def test_key_storage_failure_does_not_replace_existing_settings(client, monkeypatch):
    enable_model(monkeypatch)
    previous = (config.DATA_DIR / 'settings.json').read_text()

    def fail(_):
        raise RuntimeError('secret failure detail')

    monkeypatch.setattr(config, 'encrypt_secret', fail)
    payload = {
        'base_url': 'https://example.com',
        'model': 'test',
        'temperature': 0.5,
        'timeout': 30,
        'api_key': 'new-secret',
    }
    response = client.patch('/api/settings', json=payload)
    assert response.status_code == 503
    assert 'secret failure detail' not in response.text
    assert (config.DATA_DIR / 'settings.json').read_text() == previous
