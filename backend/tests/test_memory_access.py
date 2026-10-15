import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from backend.app import access, config, main, runtime
from backend.app.memory import summarize
from backend.app.store import Store


def test_memory_lifecycle_and_restart(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize()
    assert store.list_memories() == []
    cid = store.create_conversation()['id']
    message = store.add_message(cid, 'user', '我住在上海。')
    items = store.add_candidates(
        cid, [{'key': '城市', 'value': '上海', 'evidence': '我住在上海', 'source_message_id': message['id']}]
    )
    assert store.list_memories() == []
    saved = store.confirm_candidates([{'id': items[0]['id'], 'key': '城市', 'value': '上海'}])
    restarted = Store(store.path)
    restarted.initialize()
    assert restarted.list_memories()[0]['value'] == '上海'
    conflicting = restarted.add_candidates(
        cid, [{'key': '城市', 'value': '杭州', 'evidence': '我搬到了杭州', 'source_message_id': message['id']}]
    )
    assert conflicting[0]['existing_value'] == '上海'
    restarted.confirm_candidates([{'id': conflicting[0]['id'], 'key': '城市', 'value': '杭州'}])
    assert len(restarted.list_memories()) == 1
    restarted.edit_memory(saved[0]['id'], '苏州')
    assert restarted.list_memories()[0]['source_message_id'] is None
    restarted.delete_memory(saved[0]['id'])
    assert Store(store.path).list_memories() == []


def test_summary_requires_user_verbatim_evidence():
    history = [
        {'id': 'u', 'role': 'user', 'status': 'complete', 'content': '我住在上海。如果我是叶瞬光，我住在新艾利都。'},
        {'id': 'a', 'role': 'assistant', 'status': 'complete', 'content': '你28岁了。'},
    ]

    class Model:
        async def ainvoke(self, messages):
            assert '你28岁了' not in messages[-1].content
            return AIMessage(
                content=json.dumps(
                    {
                        'candidates': [
                            {'key': '城市', 'value': '上海', 'evidence': '我住在上海', 'source_message_id': 'u'},
                            {'key': '年龄', 'value': '28', 'evidence': '你28岁了', 'source_message_id': 'a'},
                            {
                                'key': '世界',
                                'value': '新艾利都',
                                'evidence': '如果我是叶瞬光，我住在新艾利都',
                                'source_message_id': 'u',
                            },
                            {'key': '职业', 'value': '医生', 'evidence': '我住在上海', 'source_message_id': 'u'},
                        ]
                    },
                    ensure_ascii=False,
                )
            )

    assert asyncio.run(summarize(Model(), history)) == [
        {'key': '城市', 'value': '上海', 'evidence': '我住在上海', 'source_message_id': 'u'}
    ]


def test_confirm_is_atomic_and_candidates_single_use(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize()
    cid = store.create_conversation()['id']
    msg = store.add_message(cid, 'user', '我喜欢茶')
    candidate = store.add_candidates(
        cid, [{'key': '喜好', 'value': '茶', 'evidence': '我喜欢茶', 'source_message_id': msg['id']}]
    )[0]
    item = {'id': candidate['id'], 'key': '喜好', 'value': '茶'}
    with pytest.raises(ValueError):
        store.confirm_candidates([item, {**item, 'id': 'missing'}])
    assert store.list_memories() == []
    store.confirm_candidates([item])
    with pytest.raises(ValueError):
        store.confirm_candidates([item])


def test_streaming_record_recovers_on_restart(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize()
    cid = store.create_conversation()['id']
    store.add_message(cid, 'assistant', '部分文本', 'streaming')
    reopened = Store(store.path)
    reopened.initialize()
    assert reopened.messages(cid)[0]['status'] == 'interrupted'


def test_lan_auth_protects_data_and_cross_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(runtime, 'store', Store(tmp_path / 'test.db'))
    monkeypatch.setenv('SHUNGUANG_LAN_MODE', '1')
    access.sessions.clear()
    access.attempts.clear()
    access.save_password('unit-access-password')
    assert 'unit-access-password' not in (tmp_path / 'access.json').read_text()
    with TestClient(main.app) as client:
        assert client.get('/api/auth/status').json() == {'required': True, 'authenticated': False}
        for path in ('/api/settings', '/api/conversations', '/api/voice/references', '/docs'):
            assert client.get(path).status_code == 401
        assert client.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
        response = client.post('/api/auth/login', json={'password': 'unit-access-password'})
        assert response.status_code == 200
        assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
        assert client.get('/api/settings').status_code == 200
        assert client.patch('/api/settings', headers={'Origin': 'https://evil.example'}, json={}).status_code == 403
        assert client.get('/api/settings', headers={'Host': 'evil.example'}).status_code == 403


def test_profiles_do_not_forward_keys_to_other_hosts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    config.save_config(
        config.ModelConfig(
            llm_base_url='https://api.deepseek.com',
            llm_protocol='openai',
            llm_api_key='deep-test-key',
            llm_model='deep-test',
        )
    )
    assert config.find_saved_config('https://evil.example', 'openai') is None
    assert (
        config.find_saved_config('https://api.deepseek.com/anthropic', 'anthropic').llm_api_key.get_secret_value()
        == 'deep-test-key'
    )
    config.save_config(
        config.ModelConfig(
            llm_base_url='https://api.xiaomimimo.com/v1', llm_api_key='mimo-test-key', llm_model='mimo-test'
        )
    )
    assert len(config.saved_profiles()) == 2
    assert (
        config.find_saved_config('https://api.deepseek.com', 'openai').llm_api_key.get_secret_value() == 'deep-test-key'
    )
    raw = (tmp_path / 'settings.json').read_text()
    assert 'deep-test-key' not in raw and 'mimo-test-key' not in raw
