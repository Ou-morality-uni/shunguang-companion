import asyncio

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from backend.app import config, feature_config, main, memory, rag, retrieval_router, runtime, tools
from backend.app.routes import chat
from backend.app.store import Store


def test_personal_questions_do_not_touch_lore(monkeypatch):
    monkeypatch.setattr(retrieval_router, 'entities', lambda: {'邦布', '六分街', '叶瞬光'})
    for question in ['你知道我是哪里人吗？', '你记得我吗', '上个聊天框聊了什么', '贺州天气', '你好', '你是谁？']:
        assert not retrieval_router.route(question)['search']
    assert retrieval_router.route('邦布是什么')['search']
    assert retrieval_router.route('六分街在哪里')['search']
    assert retrieval_router.relevant_sources(
        '邦布是什么', [{'title': '六分街', 'text': '录像店'}, {'title': '邦布', 'text': '小型设备'}]
    ) == [{'title': '邦布', 'text': '小型设备'}]


def test_auto_facts_shared_and_forgetting_blocks_old_retrieval(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.initialize()
    first = store.create_conversation()['id']
    second = store.create_conversation()['id']
    message = store.add_message(first, 'user', '我是贺州人，你要记住了')
    result = asyncio.run(memory.update_from_message(store, object(), message, feature_config.MemoryConfig(), [message]))
    assert result['status'] == 'saved'
    assert store.list_memories()[0]['value'] == '贺州'
    assert store.recall_history('贺州', second)[0]['message_id'] == message['id']
    store.update_summary(first)
    store.delete_memory(store.list_memories()[0]['id'])
    assert store.recall_history('贺州', second) == []
    assert (
        store.add_candidates(
            first, [{'key': '家乡', 'value': '贺州', 'evidence': '我是贺州人', 'source_message_id': message['id']}]
        )
        == []
    )
    new = store.add_message(second, 'user', '我是贺州人')
    assert (
        asyncio.run(memory.update_from_message(store, object(), new, feature_config.MemoryConfig(), [new]))['status']
        == 'saved'
    )


def test_unsupported_inferences_and_roleplay_are_not_stored():
    for text in [
        '假设我是贺州人',
        '“我是贺州人”是台词',
        '你觉得我是哪里人？',
        '我扮演六分街居民',
        '我的密钥是 sk-private',
    ]:
        assert memory.direct_facts(text) == []
    assert memory.direct_facts('我是贺州人')[0]['key'] == '家乡'
    assert memory.direct_facts('我现在住在南宁了')[0]['key'] == '居住地'
    assert memory.direct_facts('我是程序员') == []
    assert memory.direct_facts('我来自贺州')[0]['value'] == '贺州'


def test_questions_about_forgetting_and_negative_reminders_do_not_delete_facts():
    for text in ['你忘记我是贺州人了吗？', '不要忘记我是贺州人', '你是不是忘掉我说的话了？']:
        assert not memory.forget_request(text)
    assert memory.forget_request('请忘掉我的家乡')
    assert memory.forget_request('删除所有记忆')


def test_forgetting_a_manually_reworded_fact_excludes_its_original_turn(tmp_path):
    store = Store(tmp_path / 'facts.db')
    store.initialize()
    cid = store.create_conversation()['id']
    other = store.create_conversation()['id']
    user = store.add_message(cid, 'user', '我是贺州人')
    store.add_message(cid, 'assistant', '贺州呀，我记得了。')
    candidate = store.add_candidates(
        cid, [{'key': '家乡', 'value': '贺州', 'evidence': '我是贺州人', 'source_message_id': user['id']}]
    )[0]
    saved = store.confirm_candidates([{'id': candidate['id'], 'key': '家乡', 'value': '用户来自广西贺州'}])[0]
    store.delete_memory(saved['id'])
    assert store.recall_history('贺州', other) == []
    assert (
        store.add_candidates(
            cid, [{'key': '家乡', 'value': '贺州', 'evidence': '我是贺州人', 'source_message_id': user['id']}]
        )
        == []
    )


def test_chat_writes_before_reply_and_new_conversation_skips_rag(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'store', Store(tmp_path / 'chat.db'))
    config.save_config(config.ModelConfig(llm_model='test', llm_api_key='test-only'))
    monkeypatch.setattr(tools, 'schemas', lambda _: [])

    def forbidden():
        raise AssertionError('personal question must not inspect RAG')

    monkeypatch.setattr(rag, 'status', forbidden)
    seen = []

    class Model:
        async def astream(self, history):
            seen.append('\n'.join(str(x.content) for x in history))
            assert runtime.store.list_memories()[0]['value'] == '贺州'
            yield AIMessageChunk(content='记得呀，贺州。')

    monkeypatch.setattr(chat, 'build_model', lambda _: Model())
    with TestClient(main.app) as client:
        first = client.post('/api/chat', json={'content': '我是贺州人，你要记住了'})
        assert 'event: done' in first.text
        second = client.post('/api/chat', json={'content': '你知道我是哪里人吗？'})
        assert 'event: done' in second.text and 'event: sources' not in second.text
        records = client.get('/api/conversations').json()
        assert len(records) == 2
        last = client.get(f'/api/conversations/{records[0]["id"]}/messages').json()[-1]
        assert last['sources'] == [] and last['context_sources'] == []
    assert '贺州' in seen[-1]


def test_citations_only_expose_references_named_by_model():
    context = [{'number': 1, 'text': '邦布'}, {'number': 2, 'text': '六分街'}]
    assert retrieval_router.cited_sources('这是一条事实。[1]', context) == [
        {'number': 1, 'text': '邦布', 'usage': 'cited'}
    ]
    assert retrieval_router.cited_sources('这是个人记忆。', context) == []


def test_lore_sources_match_the_requested_entity_and_fact(monkeypatch):
    monkeypatch.setattr(retrieval_router, 'entities', lambda: {'叶瞬光', '邦布', '六分街'})
    candidates = [
        {'title': '叶瞬光 · 性格', 'text': '温柔可靠'},
        {'title': '叶瞬光 · 姓名与阵营', 'text': '云岿山'},
        {'title': '其他阵营', 'text': '听说过叶瞬光'},
    ]
    assert retrieval_router.relevant_sources('叶瞬光属于哪个阵营', candidates) == [candidates[1]]


def test_feature_memory_preferences_are_persisted():
    result = feature_config.update({'memory': {'auto_save': False, 'recall_history': False}})
    assert not result.memory.auto_save
    assert feature_config.public(feature_config.load())['memory']['recall_history'] is False
