from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import runtime
from backend.app.routes import chat
from backend.app.store import Store


def test_messages_default_to_recent_page_and_support_both_cursor_directions(tmp_path, monkeypatch):
    store = Store(tmp_path / 'messages.sqlite3')
    store.initialize()
    monkeypatch.setattr(runtime, 'store', store)
    cid = store.create_conversation()['id']
    for index in range(202):
        store.add_message(cid, 'user', str(index))
    app = FastAPI()
    app.include_router(chat.router)
    with TestClient(app) as client:
        latest = client.get(f'/api/conversations/{cid}/messages').json()
        assert len(latest) == 200
        assert latest[0]['content'] == '2'
        earlier = client.get(f'/api/conversations/{cid}/messages?before={latest[0]["seq"]}').json()
        assert [message['content'] for message in earlier] == ['0', '1']
        newer = client.get(f'/api/conversations/{cid}/messages?after={latest[-2]["seq"]}').json()
        assert [message['content'] for message in newer] == ['201']
