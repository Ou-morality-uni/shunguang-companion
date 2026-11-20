from fastapi.testclient import TestClient

from backend.app import main, runtime
from backend.app.store import Store


def test_upload_records_are_compact_and_do_not_expose_local_paths(tmp_path, monkeypatch):
    store = Store(tmp_path / 'uploads.sqlite3')
    monkeypatch.setattr(runtime, 'store', store)
    with TestClient(main.app) as client:
        uploaded = client.post('/api/work/upload?name=notes.txt', content=b'Notes').json()['task']
        records = client.get('/api/work/uploads').json()
        assert records == [
            {'id': uploaded['id'], 'name': 'notes.txt', 'bytes': 5, 'created_at': uploaded['created_at']}
        ]
        assert not any(key in records[0] for key in ('path', 'steps', 'workspace_id'))
