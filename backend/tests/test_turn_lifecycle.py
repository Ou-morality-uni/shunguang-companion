import asyncio

import pytest

from backend.app import config, runtime
from backend.app.routes import chat
from backend.app.store import Store


def test_unconsumed_response_releases_reservation_without_calling_model(tmp_path, monkeypatch):
    from backend.app import turn_lifecycle

    monkeypatch.setattr(turn_lifecycle, 'START_TIMEOUT', 0.02)
    store = Store(tmp_path / 'turn.sqlite3')
    store.initialize()
    monkeypatch.setattr(runtime, 'store', store)
    monkeypatch.setattr(chat, 'build_model', lambda _: object())
    config.save_config(config.ModelConfig(llm_model='synthetic', llm_api_key='synthetic-key'))

    async def run():
        runtime.mutation_lock = asyncio.Lock()
        response = await chat.generate_chat(chat.ChatRequest(content='hello'))
        await asyncio.sleep(0.1)
        cid = store.list_conversations()[0]['id']
        assert cid not in runtime.busy
        assert store.messages(cid)[-1]['status'] == 'interrupted'
        return response

    asyncio.run(run())


def test_cancel_before_first_response_body_releases_turn(tmp_path, monkeypatch):
    store = Store(tmp_path / 'cancel.sqlite3')
    store.initialize()
    monkeypatch.setattr(runtime, 'store', store)
    monkeypatch.setattr(chat, 'build_model', lambda _: object())
    config.save_config(config.ModelConfig(llm_model='synthetic', llm_api_key='synthetic-key'))

    async def run():
        runtime.mutation_lock = asyncio.Lock()
        response = await chat.generate_chat(chat.ChatRequest(content='cancel before body'))

        async def receive():
            return {'type': 'http.disconnect'}

        async def send(message):
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await response({'type': 'http', 'asgi': {'spec_version': '2.4'}, 'method': 'POST'}, receive, send)
        cid = store.list_conversations()[0]['id']
        assert cid not in runtime.busy
        assert store.messages(cid)[-1]['status'] == 'interrupted'

    asyncio.run(run())
