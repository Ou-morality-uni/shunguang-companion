import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import runtime
from backend.app.filework import FileWork
from backend.app.routes import chat
from backend.app.store import Store
from backend.app.work_artifacts import attachment


def test_delete_cleans_exclusive_upload_but_retains_shared_copy(tmp_path, monkeypatch):
    store = Store(tmp_path / 'chat.sqlite3')
    store.initialize()
    work = FileWork(store)
    monkeypatch.setattr(runtime, 'store', store)
    monkeypatch.setattr(runtime, 'work', work)
    monkeypatch.setattr(runtime, 'qq', None)
    monkeypatch.setattr(runtime, 'mutation_lock', asyncio.Lock())
    one, two = [store.create_conversation()['id'] for _ in range(2)]
    solo = work.upload('solo.txt', b'exclusive')
    shared = work.upload('shared.txt', b'shared')
    solo_ref, shared_ref = [attachment(work, item['task']['id']) for item in (solo, shared)]
    store.add_message(one, 'user', 'files', metadata={'attachments': [solo_ref, shared_ref]})
    store.add_message(two, 'user', 'keep', metadata={'attachments': [shared_ref]})
    app = FastAPI()
    app.include_router(chat.router)
    try:
        with TestClient(app) as client:
            assert client.delete(f'/api/conversations/{one}').status_code == 204
        assert not (work.upload_root / solo['path']).exists()
        assert (work.upload_root / shared['path']).read_bytes() == b'shared'
        assert store.get_file_task(solo['task']['id']) is None
        assert store.get_file_task(shared['task']['id']) is not None
    finally:
        work.close()


def test_database_failure_restores_staged_files(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import contextmanager

    import pytest

    from backend.app.conversation_cleanup import delete

    store = Store(tmp_path / 'chat.sqlite3')
    store.initialize()
    work = FileWork(store)
    cid = store.create_conversation()['id']
    uploaded = work.upload('keep.txt', b'keep')
    store.add_message(cid, 'user', 'file', metadata={'attachments': [attachment(work, uploaded['task']['id'])]})
    connect = store.connect

    @contextmanager
    def failing_commit():
        with connect() as db:
            db.set_authorizer(
                lambda action, table, *args: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_DELETE and table == 'conversations'
                    else sqlite3.SQLITE_OK
                )
            )
            yield db

    monkeypatch.setattr(store, 'connect', failing_commit)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            delete(work, cid)
        assert (work.upload_root / uploaded['path']).read_bytes() == b'keep'
        assert store.get_conversation(cid)
        assert store.get_file_task(uploaded['task']['id'])
        assert list((tmp_path / 'deletion-journal').glob('*/plan.json')) == []
    finally:
        work.close()


def test_generated_artifacts_are_removed_but_workspace_source_survives(tmp_path, monkeypatch):
    from backend.app import config
    from backend.app.conversation_cleanup import delete
    from backend.app.work_artifacts import save_file

    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'data')
    store = Store(config.DATA_DIR / 'chat.sqlite3')
    store.initialize()
    work = FileWork(store)
    cid = store.create_conversation()['id']
    source = tmp_path / 'source'
    source.mkdir()
    original = source / 'original.txt'
    original.write_text('original', encoding='utf-8')
    workspace = work.grant(str(source))
    task = store.create_file_task(workspace['id'], 'generated', [], 'complete', origin='chat', conversation_id=cid)
    try:
        one = save_file(work, task, 'one.txt', b'one', {})
        two = save_file(work, task, 'two.txt', b'two', {})
        paths = [work.path(work.root(item['workspace_id']), item['path']) for item in (one, two)]
        assert delete(work, cid)
        assert all(not path.exists() for path in paths)
        assert original.read_text(encoding='utf-8') == 'original'
    finally:
        work.close()
