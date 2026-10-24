import asyncio

from fastapi.testclient import TestClient

from backend.app import feature_config, main, memory, runtime
from backend.app.store import Store


def test_profile_starts_with_a_default_address_and_optional_details(tmp_path, monkeypatch):
    store = Store(tmp_path / 'profile.sqlite3')
    monkeypatch.setattr(runtime, 'store', store)
    with TestClient(main.app) as client:
        response = client.get('/api/profile')
        assert response.status_code == 200
        assert response.json() == {'nickname': '小师妹', 'city': '', 'age': None}


def test_profile_edits_are_durable_user_facts_and_can_be_cleared(tmp_path, monkeypatch):
    store = Store(tmp_path / 'profile.sqlite3')
    monkeypatch.setattr(runtime, 'store', store)
    with TestClient(main.app) as client:
        response = client.patch('/api/profile', json={'nickname': '小师弟', 'city': '南宁', 'age': 23})
        assert response.status_code == 200
        assert response.json() == {'nickname': '小师弟', 'city': '南宁', 'age': 23}
        assert {item['key']: item['value'] for item in store.list_memories()} == {
            '对用户的称呼': '小师弟',
            '居住地': '南宁',
            '年龄': '23',
        }
        restarted = Store(store.path)
        assert restarted.user_profile()['city'] == '南宁'
        assert client.patch('/api/profile', json={'city': '', 'age': None}).status_code == 200
        assert client.get('/api/profile').json() == {'nickname': '小师弟', 'city': '', 'age': None}
        assert client.patch('/api/profile', json={'age': -2}).status_code == 422
        assert client.patch('/api/profile', json={'age': True}).status_code == 422
        assert client.get('/api/profile').json()['age'] is None


def test_temporary_stay_preserves_residence_but_an_explicit_move_updates_it(tmp_path):
    store = Store(tmp_path / 'profile.sqlite3')
    store.initialize()
    store.update_user_profile({'city': '贺州'})
    cid = store.create_conversation()['id']
    for text, expected in [('我现在住在南宁的酒店，玩两天就回去。', '贺州'), ('我搬到南宁了。', '南宁')]:
        message = store.add_message(cid, 'user', text)
        asyncio.run(memory.update_from_message(store, object(), message, feature_config.MemoryConfig(), [message]))
        assert store.user_profile()['city'] == expected


def test_clear_chat_statements_update_the_address_and_age_in_the_same_profile(tmp_path):
    store = Store(tmp_path / 'profile.sqlite3')
    store.initialize()
    cid = store.create_conversation()['id']
    message = store.add_message(cid, 'user', '以后叫我小师弟，我今年23岁。')
    result = asyncio.run(memory.update_from_message(store, object(), message, feature_config.MemoryConfig(), [message]))
    assert result['status'] == 'saved'
    assert store.user_profile() == {'nickname': '小师弟', 'city': '', 'age': 23}
