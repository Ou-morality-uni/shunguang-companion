import asyncio
from contextlib import contextmanager

from backend.app.qq.repository import QQRepository
from backend.app.qq.service import QQService


def test_disabled_qq_does_not_poll_database(tmp_path, monkeypatch):
    repo = QQRepository(tmp_path / 'qq')
    statements = []
    connect = repo.connect

    @contextmanager
    def traced():
        with connect() as db:
            db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr(repo, 'connect', traced)

    async def run():
        service = QQService(repo)
        await service.start()
        await asyncio.sleep(0.05)
        statements.clear()
        await asyncio.sleep(0.3)
        assert statements == []
        await service.close()

    asyncio.run(run())


def test_old_empty_isolated_scope_is_reclaimed(tmp_path):
    import os
    import time

    repo = QQRepository(tmp_path / 'qq')
    service = QQService(repo)
    store, _, key = service.scope('10001', 'private', '30001', '30001')
    os.utime(store.path, (time.time() - 40 * 86400,) * 2)
    repo.cleanup(time.time())
    assert not store.path.exists()
    assert all(item['key'] != key for item in repo.scopes())
