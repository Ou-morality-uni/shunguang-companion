import asyncio

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk, ToolMessage

from backend.app import config, main, rag, runtime, tools
from backend.app.routes import chat as chat_routes
from backend.app.store import Store


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(runtime, 'store', Store(tmp_path / 'test.db'))
    monkeypatch.setattr(rag, 'status', lambda: {'ready': False})
    config.save_config(
        config.ModelConfig(llm_base_url='https://example.com/v1', llm_model='test', llm_api_key='test-only')
    )
    runtime.busy.clear()
    runtime.stops.clear()


def test_agent_returns_actual_tool_result_then_persists(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    received = []

    class Model:
        def bind_tools(self, schemas):
            return self

        async def astream(self, history):
            if isinstance(history[-1], ToolMessage):
                received.append(history[-1].content)
                yield AIMessageChunk(content='数据返回：19度。')
            else:
                yield AIMessageChunk(
                    content='', tool_calls=[{'name': 'weather', 'id': 'tool1', 'args': {'city': '上海'}}]
                )

    async def execute(name, args):
        assert name == 'weather' and args == {'city': '上海'}
        return {'ok': True, 'temperature': 19, 'sources': [{'title': 'source', 'url': 'https://example.com/weather'}]}

    monkeypatch.setattr(chat_routes, 'build_model', lambda _: Model())
    monkeypatch.setattr(tools, 'execute', execute)
    with TestClient(main.app) as client:
        cid = client.post('/api/conversations').json()['id']
        response = client.post('/api/chat', json={'conversation_id': cid, 'content': '上海天气'})
        assert 'event: tool' in response.text and 'event: done' in response.text
        assert '19' in received[0]
        record = client.get(f'/api/conversations/{cid}/messages').json()[-1]
        assert record['tools'][0]['result']['temperature'] == 19
        assert record['status'] == 'complete'


def test_agent_caps_executions_and_rejects_unregistered_tool(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    executed = []

    class Model:
        def bind_tools(self, schemas):
            return self

        async def astream(self, history):
            if len([m for m in history if isinstance(m, ToolMessage)]) >= 10:
                yield AIMessageChunk(content='已到调用上限。')
                return
            yield AIMessageChunk(
                content='',
                tool_calls=[
                    {'name': 'weather' if i < 4 else 'run_shell', 'id': f'{len(history)}-{i}', 'args': {'city': '上海'}}
                    for i in range(5)
                ],
            )

    async def execute(name, args):
        executed.append(name)
        return {'ok': True}

    monkeypatch.setattr(chat_routes, 'build_model', lambda _: Model())
    monkeypatch.setattr(tools, 'execute', execute)
    with TestClient(main.app) as client:
        cid = client.post('/api/conversations').json()['id']
        response = client.post('/api/chat', json={'conversation_id': cid, 'content': '循环测试'})
        assert response.status_code == 200
        assert executed == ['weather'] * 4
        assert '调用次数已达上限' in response.text


def test_explicit_stop_persists_interruption(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    monkeypatch.setattr(tools, 'schemas', lambda _: [])

    class Model:
        async def astream(self, history):
            yield AIMessageChunk(content='部分')
            await asyncio.sleep(30)

    monkeypatch.setattr(chat_routes, 'build_model', lambda _: Model())
    runtime.store.initialize()
    cid = runtime.store.create_conversation()['id']

    async def run():
        response = await chat_routes.chat(chat_routes.ChatRequest(conversation_id=cid, content='停止测试'))
        iterator = response.body_iterator
        await anext(iterator)
        await anext(iterator)

        async def drain():
            return [frame async for frame in iterator]

        draining = asyncio.create_task(drain())
        await chat_routes.stop_chat(cid)
        assert runtime.store.messages(cid)[-1]['status'] == 'interrupted'
        remaining = await draining
        assert 'interrupted' in ''.join(remaining)

    asyncio.run(run())
    assert runtime.store.messages(cid)[-1]['content'] == '部分'
    assert runtime.store.messages(cid)[-1]['status'] == 'interrupted'
    assert cid not in runtime.busy
