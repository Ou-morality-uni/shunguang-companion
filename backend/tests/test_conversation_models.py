import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from backend.app import config, main, runtime
from backend.app.routes import chat, settings
from backend.app.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'state')
    assert config.DATA_DIR.is_relative_to(tmp_path)
    store = Store(config.DATA_DIR / 'models.sqlite3')
    monkeypatch.setattr(runtime, 'store', store)
    config.save_config(
        config.ModelConfig(llm_base_url='https://one.example/v1', llm_model='model-one', llm_api_key='private-one')
    )
    config.save_config(
        config.ModelConfig(llm_base_url='https://two.example/v1', llm_model='model-two', llm_api_key='private-two')
    )
    with TestClient(main.app) as value:
        yield value


def test_conversation_model_choice_is_durable_and_does_not_change_other_chats_or_global_default(client):
    first = client.post('/api/conversations').json()['id']
    second = client.post('/api/conversations').json()['id']
    choice = {
        'profile_id': config.profile_id('https://one.example/v1', 'openai'),
        'model': 'model-one',
        'effort': 'default',
    }
    changed = client.patch(f'/api/conversations/{first}/model', json=choice)
    assert changed.status_code == 200
    assert {key: changed.json()[key] for key in choice} == choice
    assert client.get(f'/api/conversations/{second}/model').json()['model'] == 'model-two'
    assert client.get(f'/api/conversations/{first}/model').json()['model'] == 'model-one'
    assert Store(runtime.store.path).conversation_model(first)['model'] == 'model-one'
    assert config.load_config().llm_model == 'model-two'
    assert 'private-one' not in changed.text and 'private-two' not in changed.text


def test_chat_uses_its_selected_connection_instead_of_the_global_default(client, monkeypatch):
    seen = []

    class Model:
        async def astream(self, messages):
            yield AIMessageChunk(content='你好。')

    def build(value):
        seen.append((value.llm_base_url, value.llm_model))
        return Model()

    monkeypatch.setattr(chat, 'build_model', build)
    cid = client.post('/api/conversations').json()['id']
    client.patch(
        f'/api/conversations/{cid}/model',
        json={
            'profile_id': config.profile_id('https://one.example/v1', 'openai'),
            'model': 'model-one',
            'effort': 'default',
        },
    )
    response = client.post('/api/chat', json={'conversation_id': cid, 'content': '你好'})
    assert response.status_code == 200 and 'event: done' in response.text
    assert seen == [('https://one.example/v1', 'model-one')]


def test_model_menu_groups_saved_connections_and_only_lists_verified_effort_controls(client):
    config.save_config(
        config.ModelConfig(
            llm_base_url='https://api.deepseek.com', llm_model='deepseek-flash', llm_api_key='private-deepseek'
        )
    )
    response = client.get('/api/model-options')
    assert response.status_code == 200
    entries = {item['id']: item for item in response.json()}
    custom = entries[config.profile_id('https://one.example/v1', 'openai')]
    assert custom['models'][0]['efforts'] == []
    native = entries[config.profile_id('https://api.deepseek.com', 'openai')]
    assert native['models'][0]['efforts'] == ['low', 'high', 'max']
    assert native['models'][0]['initial_effort'] == 'high'
    assert 'private-deepseek' not in response.text


def test_model_discovery_uses_the_selected_saved_key_and_populates_the_quick_menu(client, monkeypatch):
    calls = []

    async def discover(value):
        calls.append((value.llm_base_url, value.llm_api_key.get_secret_value()))
        return {'models': [{'id': 'model-one'}, {'id': 'additional-model'}]}

    monkeypatch.setattr(settings, 'discover', discover)
    pid = config.profile_id('https://one.example/v1', 'openai')
    response = client.post(f'/api/model-options/{pid}/refresh')
    assert response.status_code == 200
    assert [item['id'] for item in response.json()['models']] == ['model-one', 'additional-model']
    assert calls == [('https://one.example/v1', 'private-one')]
    group = next(item for item in client.get('/api/model-options').json() if item['id'] == pid)
    assert [item['id'] for item in group['models']] == ['model-one', 'additional-model']
    cid = client.post('/api/conversations').json()['id']
    assert (
        client.patch(
            f'/api/conversations/{cid}/model',
            json={'profile_id': pid, 'model': 'additional-model', 'effort': 'default'},
        ).status_code
        == 200
    )


def test_settings_default_effort_is_used_only_by_new_conversations(client):
    previous = client.post('/api/conversations').json()['id']
    first = client.get(f'/api/conversations/{previous}/model').json()
    client.patch(
        f'/api/conversations/{previous}/model', json={key: first[key] for key in ('profile_id', 'model', 'effort')}
    )
    response = client.patch(
        '/api/settings',
        json={
            'base_url': 'https://api.deepseek.com',
            'model': 'deepseek-flash',
            'api_key': 'test-default-only',
            'temperature': 0.7,
            'timeout': 45,
            'effort': 'high',
        },
    )
    assert response.status_code == 200
    assert response.json()['effort'] == 'high'
    assert client.get('/api/model-default').json()['effort'] == 'high'
    new = client.post('/api/conversations').json()['id']
    assert client.get(f'/api/conversations/{new}/model').json()['effort'] == 'high'
    assert client.get(f'/api/conversations/{previous}/model').json()['model'] == 'model-two'


def test_invalid_or_missing_model_choices_never_fall_back_to_another_service(client, monkeypatch):
    calls = []
    monkeypatch.setattr(chat, 'build_model', lambda value: calls.append(value))
    cid = client.post('/api/conversations').json()['id']
    current = client.get(f'/api/conversations/{cid}/model').json()
    choice = {key: current[key] for key in ('profile_id', 'model', 'effort')}
    invalid = {**choice, 'effort': 'high'}
    assert client.patch(f'/api/conversations/{cid}/model', json=invalid).status_code == 422
    assert (
        client.post('/api/chat', json={'conversation_id': cid, 'content': '你好', 'model_choice': invalid}).status_code
        == 422
    )
    missing = {**choice, 'profile_id': 'removed-connection'}
    assert (
        client.post('/api/chat', json={'conversation_id': cid, 'content': '你好', 'model_choice': missing}).status_code
        == 409
    )
    assert calls == []
    assert client.get(f'/api/conversations/{cid}/messages').json() == []
    assert config.load_config().llm_model == 'model-two'
