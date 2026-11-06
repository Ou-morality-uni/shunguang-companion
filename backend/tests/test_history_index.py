from contextlib import contextmanager

from backend.app.store import Store


def test_chinese_history_lookup_has_bounded_database_work(tmp_path, monkeypatch):
    store = Store(tmp_path / 'history.sqlite3')
    store.initialize()
    old = store.create_conversation()['id']
    current = store.create_conversation()['id']
    with store.connect() as db:
        db.executemany(
            "INSERT INTO messages(id,conversation_id,role,content,status,created_at) VALUES (?,?,'user',?,'complete','2026-10-30T00:00:00Z')",
            [(f'ordinary-{i}', old, f'日常讨论示例 {i}') for i in range(1500)],
        )
    target = store.add_message(old, 'user', '特殊暗号对应的已确认决定是橙色。')
    original_connect = store.connect

    @contextmanager
    def bounded_connect():
        with original_connect() as db:
            remaining = 100

            def progress():
                nonlocal remaining
                remaining -= 1
                return remaining <= 0

            db.set_progress_handler(progress, 100)
            yield db

    monkeypatch.setattr(store, 'connect', bounded_connect)
    assert store.recall_history('特殊暗号', current)[0]['message_id'] == target['id']
