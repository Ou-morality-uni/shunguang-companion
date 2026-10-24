import json
import time
from threading import Event

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from backend.app import config, main, runtime
from backend.app.routes import chat
from backend.app.store import Store


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'state')
    assert config.DATA_DIR.is_relative_to(tmp_path)
    store = Store(config.DATA_DIR / 'memory.sqlite3')
    store.initialize()
    monkeypatch.setattr(runtime, 'store', store)
    config.save_config(
        config.ModelConfig(llm_base_url='https://memory.test/v1', llm_model='test', llm_api_key='offline-only')
    )
    seen = []

    class Model:
        async def astream(self, messages):
            seen.append(messages)
            yield AIMessageChunk(content='我们接着核对。')

    monkeypatch.setattr(chat, 'build_model', lambda value: Model())
    return store, seen


def test_new_chat_automatically_recalls_a_relevant_old_message_and_returns_its_source(setup):
    store, seen = setup
    old = store.create_conversation()['id']
    source = store.add_message(old, 'user', '预算表里交通费是320元，需要留着核对。')
    with TestClient(main.app) as client:
        current = client.post('/api/conversations').json()['id']
        response = client.post('/api/chat', json={'conversation_id': current, 'content': '预算表接着核对一下。'})
        assert 'event: done' in response.text
        assert any('交通费是320元' in str(messages) for messages in seen)
        record = client.get(f'/api/conversations/{current}/messages').json()[-1]
        assert record['history_sources'][0]['message_id'] == source['id']
        assert record['history_sources'][0]['conversation_id'] == old


def test_background_summary_extracts_stable_facts_without_holding_up_chat_and_keeps_progress_on_restart(
    setup, monkeypatch
):
    from backend.app import memory_jobs

    store, _ = setup
    cid = store.create_conversation()['id']
    source = store.add_message(cid, 'user', '空闲的时候我常去打羽毛球。')
    started, release = Event(), Event()
    calls = []

    class Model:
        async def ainvoke(self, messages):
            calls.append(messages)
            started.set()
            assert release.wait(5)
            return AIMessage(
                content=json.dumps(
                    {
                        'summary': '用户空闲时常打羽毛球。',
                        'evidence': [{'source_message_id': source['id'], 'quote': '我常去打羽毛球'}],
                        'candidates': [
                            {
                                'key': '运动偏好',
                                'value': '羽毛球',
                                'evidence': '我常去打羽毛球',
                                'source_message_id': source['id'],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )

    monkeypatch.setattr(memory_jobs, 'build_memory_model', lambda value: Model())
    try:
        with TestClient(main.app) as client:
            assert started.wait(1), 'background backfill did not start'
            response = client.post('/api/chat', json={'content': '你好'})
            assert 'event: done' in response.text
            assert not release.is_set(), 'chat must finish before background extraction'
            release.set()
            for _ in range(100):
                memories = client.get('/api/memories').json()
                if any(item['value'] == '羽毛球' for item in memories):
                    break
                time.sleep(0.01)
            assert any(item['value'] == '羽毛球' for item in memories)
            status = client.get('/api/memories/status').json()
            assert status['summaries'] >= 1
    finally:
        release.set()
    with TestClient(main.app) as client:
        assert any(item['value'] == '羽毛球' for item in client.get('/api/memories').json())
        assert client.get('/api/memories/status').json()['summaries'] >= 1


def test_semantic_summary_can_find_a_related_conversation_without_matching_the_old_wording(setup, monkeypatch):
    from backend.app import memory_jobs

    store, seen = setup
    old = store.create_conversation()['id']
    source = store.add_message(old, 'user', '空闲的时候我常去打羽毛球。')

    class Model:
        async def ainvoke(self, messages):
            raw = json.loads(messages[-1].content)[0]
            return AIMessage(
                content=json.dumps(
                    {
                        'summary': '用户的运动安排是打羽毛球。',
                        'evidence': [{'source_message_id': raw['id'], 'quote': raw['text']}],
                        'candidates': [],
                    },
                    ensure_ascii=False,
                )
            )

    monkeypatch.setattr(memory_jobs, 'build_memory_model', lambda value: Model())
    with TestClient(main.app) as client:
        for _ in range(100):
            if client.get('/api/memories/status').json()['summaries']:
                break
            time.sleep(0.01)
        assert client.get('/api/memories/status').json()['summaries'] == 1
        cid = client.post('/api/conversations').json()['id']
        response = client.post('/api/chat', json={'conversation_id': cid, 'content': '运动安排接着规划一下。'})
        assert 'event: done' in response.text
        assert any('我常去打羽毛球' in str(messages) for messages in seen)
        result = client.get(f'/api/conversations/{cid}/messages').json()[-1]
        assert result['history_sources'][0]['message_id'] == source['id']
        assert '运动安排' in result['history_sources'][0]['episode_summary']


def test_history_source_is_viewable_and_invalidates_after_its_conversation_is_deleted(setup):
    store, _ = setup
    old = store.create_conversation()['id']
    source = store.add_message(old, 'user', '预算表里交通费是320元，需要留着核对。')
    with TestClient(main.app) as client:
        cid = client.post('/api/conversations').json()['id']
        client.post('/api/chat', json={'conversation_id': cid, 'content': '预算表接着核对一下。'})
        result = client.get(f'/api/memories/history/{source["id"]}')
        assert result.status_code == 200
        assert result.json()['text'] == source['content']
        assert client.delete(f'/api/conversations/{old}').status_code == 204
        assert client.get(f'/api/memories/history/{source["id"]}').status_code == 404
        assert client.get(f'/api/conversations/{cid}/messages').json()[-1]['history_sources'] == []


def test_late_background_extraction_cannot_overwrite_newer_manual_profile_information(setup, monkeypatch):
    from backend.app import memory_jobs

    store, _ = setup
    cid = store.create_conversation()['id']
    source = store.add_message(cid, 'user', '我常年住在南宁。')
    started, release = Event(), Event()

    class Model:
        async def ainvoke(self, messages):
            started.set()
            assert release.wait(5)
            return AIMessage(
                content=json.dumps(
                    {
                        'summary': '用户曾自述住在南宁。',
                        'evidence': [{'source_message_id': source['id'], 'quote': '我常年住在南宁'}],
                        'candidates': [
                            {
                                'key': '居住地',
                                'value': '南宁',
                                'evidence': '我常年住在南宁',
                                'source_message_id': source['id'],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )

    monkeypatch.setattr(memory_jobs, 'build_memory_model', lambda value: Model())
    try:
        with TestClient(main.app) as client:
            assert started.wait(1)
            assert client.patch('/api/profile', json={'city': '上海'}).json()['city'] == '上海'
            release.set()
            for _ in range(100):
                status = client.get('/api/memories/status').json()
                if not status['running'] and not status['queued']:
                    break
                time.sleep(0.01)
            assert client.get('/api/profile').json()['city'] == '上海'
    finally:
        release.set()


def test_background_backfill_skips_secret_messages_and_continues_with_later_messages(setup, monkeypatch):
    from backend.app import memory_jobs

    store, _ = setup
    cid = store.create_conversation()['id']
    for number in range(12):
        store.add_message(cid, 'user', f'我的测试密码是 private-password-{number}。')
    source = store.add_message(cid, 'user', '我周末去打羽毛球。')
    seen = []

    class Model:
        async def ainvoke(self, messages):
            raw = json.loads(messages[-1].content)
            seen.append(messages[-1].content)
            return AIMessage(
                content=json.dumps(
                    {
                        'summary': '用户聊到了周末活动。',
                        'evidence': [{'source_message_id': raw[-1]['id'], 'quote': raw[-1]['text']}],
                        'candidates': [],
                    },
                    ensure_ascii=False,
                )
            )

    monkeypatch.setattr(memory_jobs, 'build_memory_model', lambda value: Model())
    with TestClient(main.app) as client:
        for _ in range(100):
            status = client.get('/api/memories/status').json()
            if not status['running'] and not status['queued']:
                break
            time.sleep(0.01)
        assert seen and all('private-password-' not in text for text in seen)
        assert any(source['id'] in text for text in seen)
        assert client.get('/api/memories/status').json()['summaries'] == 1
        current = client.post('/api/conversations').json()['id']
        client.post('/api/chat', json={'conversation_id': current, 'content': '测试密码是什么？'})
        assert client.get(f'/api/conversations/{current}/messages').json()[-1]['history_sources'] == []


def test_explicit_memory_request_does_not_invoke_extraction_in_the_reply_stream(setup, monkeypatch):
    store, _ = setup
    calls = []

    class ReplyOnly:
        async def astream(self, messages):
            yield AIMessageChunk(content='这就帮你整理。')

        async def ainvoke(self, messages):
            calls.append(messages)
            return AIMessage(content='{"candidates":[]}')

    monkeypatch.setattr(chat, 'build_model', lambda value: ReplyOnly())
    with TestClient(main.app) as client:
        response = client.post('/api/chat', json={'content': '记住，空闲的时候我常去打羽毛球。'})
        assert 'event: done' in response.text
        assert '这就帮你整理。' in response.text
        assert calls == []


def test_disabled_background_memory_resumes_existing_backlog_when_enabled(setup, monkeypatch):
    from backend.app import feature_config, memory_jobs

    store, _ = setup
    feature_config.update({'memory': {'auto_save': False, 'recall_history': False}})
    cid = store.create_conversation()['id']
    source = store.add_message(cid, 'user', '我周末去打羽毛球。')

    class Model:
        async def ainvoke(self, messages):
            return AIMessage(
                content=json.dumps(
                    {
                        'summary': '用户的周末运动是羽毛球。',
                        'evidence': [{'source_message_id': source['id'], 'quote': source['content']}],
                        'candidates': [],
                    },
                    ensure_ascii=False,
                )
            )

    monkeypatch.setattr(memory_jobs, 'build_memory_model', lambda value: Model())
    with TestClient(main.app) as client:
        for _ in range(100):
            if client.get('/api/memories/status').json()['paused']:
                break
            time.sleep(0.01)
        assert client.get('/api/memories/status').json()['paused'] == 1
        assert client.patch('/api/features', json={'memory': {'recall_history': True}}).status_code == 200
        for _ in range(100):
            if client.get('/api/memories/status').json()['summaries']:
                break
            time.sleep(0.01)
        assert client.get('/api/memories/status').json()['summaries'] == 1


def test_forgetting_removes_derived_summary_and_does_not_restore_the_fact_after_restart(setup, monkeypatch):
    from backend.app import memory_jobs

    store, _ = setup
    cid = store.create_conversation()['id']
    source = store.add_message(cid, 'user', '我周末喜欢羽毛球。')

    class Model:
        async def ainvoke(self, messages):
            return AIMessage(
                content=json.dumps(
                    {
                        'summary': '用户周末喜欢羽毛球。',
                        'evidence': [{'source_message_id': source['id'], 'quote': source['content']}],
                        'candidates': [
                            {
                                'key': '运动偏好',
                                'value': '羽毛球',
                                'evidence': source['content'],
                                'source_message_id': source['id'],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )

    monkeypatch.setattr(memory_jobs, 'build_memory_model', lambda value: Model())
    with TestClient(main.app) as client:
        for _ in range(100):
            if client.get('/api/memories/status').json()['summaries']:
                break
            time.sleep(0.01)
        facts = client.get('/api/memories').json()
        assert len(facts) == 1
        assert client.delete(f'/api/memories/{facts[0]["id"]}').status_code == 200
        assert client.get('/api/memories/status').json()['summaries'] == 0
        assert client.get(f'/api/memories/history/{source["id"]}').status_code == 404
    with TestClient(main.app) as client:
        assert client.get('/api/memories').json() == []
        assert client.get('/api/memories/status').json()['summaries'] == 0


def test_background_does_not_turn_a_roleplay_followup_into_a_real_user_preference(setup, monkeypatch):
    from backend.app import memory_jobs

    store, _ = setup
    cid = store.create_conversation()['id']
    store.add_message(cid, 'user', '我们来扮演，我扮演一个旅行者。')
    source = store.add_message(cid, 'user', '我平时常打羽毛球。')

    class Model:
        async def ainvoke(self, messages):
            return AIMessage(
                content=json.dumps(
                    {
                        'summary': '角色扮演中提到了运动。',
                        'evidence': [{'source_message_id': source['id'], 'quote': source['content']}],
                        'candidates': [
                            {
                                'key': '运动偏好',
                                'value': '羽毛球',
                                'evidence': source['content'],
                                'source_message_id': source['id'],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )

    monkeypatch.setattr(memory_jobs, 'build_memory_model', lambda value: Model())
    with TestClient(main.app) as client:
        for _ in range(100):
            if client.get('/api/memories/status').json()['summaries']:
                break
            time.sleep(0.01)
        assert client.get('/api/memories/status').json()['summaries'] == 1
        assert client.get('/api/memories').json() == []


def test_model_initiated_history_lookup_also_exposes_original_source_cards(setup, monkeypatch):
    store, _ = setup
    cid = store.create_conversation()['id']
    source = store.add_message(cid, 'user', '交通预算是320元。')

    class Model:
        def bind_tools(self, definitions):
            return self

        async def astream(self, messages):
            if isinstance(messages[-1], ToolMessage):
                yield AIMessageChunk(content='查到了，交通预算是320元。')
            else:
                yield AIMessageChunk(
                    content='',
                    tool_calls=[{'name': 'recall_conversations', 'id': 'recall', 'args': {'query': '交通预算'}}],
                )

    monkeypatch.setattr(chat, 'build_model', lambda value: Model())
    with TestClient(main.app) as client:
        response = client.post('/api/chat', json={'content': '接着聊吧'}).text
        assert 'event: done' in response
        current = next(item['id'] for item in client.get('/api/conversations').json() if item['id'] != cid)
        record = client.get(f'/api/conversations/{current}/messages').json()[-1]
        assert record['history_sources'][0]['message_id'] == source['id']
