import asyncio
import json
import os

import pytest

from backend.app import config
from backend.app.filework import FileTaskRequest, FileWork, WorkError
from backend.app.routes import chat
from backend.app.store import Store


@pytest.fixture
def work(tmp_path, monkeypatch):
    data = tmp_path / 'state'
    monkeypatch.setattr(config, 'DATA_DIR', data)
    store = Store(data / 'test.sqlite3')
    store.initialize()
    folder = tmp_path / 'files'
    folder.mkdir()
    service = FileWork(store)
    workspace = service.grant(str(folder))
    yield service, workspace['id'], folder
    service.close()


def submit(work, steps):
    service, workspace_id, _ = work
    return service.submit(FileTaskRequest(workspace_id=workspace_id, steps=steps))


def finished(service, task):
    return asyncio.run(service.wait(task['id']))


def test_edit_create_move_and_restore_actual_files(work):
    service, _, folder = work
    (folder / 'old.txt').write_text('before', encoding='utf-8')
    (folder / 'move.txt').write_bytes(b'move me')
    task = finished(
        service,
        submit(
            work,
            [
                {'action': 'write', 'path': 'old.txt', 'content': 'after'},
                {'action': 'write', 'path': 'new.txt', 'content': 'new'},
                {'action': 'move', 'path': 'move.txt', 'destination': 'moved.txt'},
                {'action': 'read', 'path': 'old.txt'},
                {'action': 'list'},
            ],
        ),
    )
    assert task['status'] == 'complete' and task['can_restore']
    assert task['steps'][3]['result']['text'] == 'after'
    assert (folder / 'old.txt').read_text() == 'after'
    assert (folder / 'moved.txt').read_bytes() == b'move me'
    assert not (folder / 'move.txt').exists()
    assert 'content' not in task['steps'][0] and 'backup' not in task['steps'][0]
    restored = finished(service, service.restore(task['id']))
    assert restored['status'] == 'restored'
    assert (folder / 'old.txt').read_text() == 'before'
    assert not (folder / 'new.txt').exists()
    assert (folder / 'move.txt').read_bytes() == b'move me'
    assert not (folder / 'moved.txt').exists()


def test_delete_requires_explicit_approval_and_cannot_reuse(work):
    service, _, folder = work
    path = folder / 'delete.txt'
    path.write_bytes(b'keep until approved')
    task = submit(
        work,
        [
            {'action': 'write', 'path': 'note.txt', 'content': 'later'},
            {'action': 'delete', 'path': 'delete.txt'},
        ],
    )
    assert task['status'] == 'waiting_approval'
    assert path.exists() and not (folder / 'note.txt').exists()
    service.approve(task['id'], False)
    assert path.exists()
    with pytest.raises(WorkError):
        service.approve(task['id'], True)
    task = submit(work, [{'action': 'delete', 'path': 'delete.txt'}])
    assert finished(service, service.approve(task['id'], True))['status'] == 'complete'
    assert not path.exists()
    assert finished(service, service.restore(task['id']))['status'] == 'restored'
    assert path.read_bytes() == b'keep until approved'


def test_approval_bound_to_original_content_and_restore_refuses_concurrent_edits(work):
    service, _, folder = work
    path = folder / 'file.txt'
    path.write_text('first')
    task = submit(work, [{'action': 'delete', 'path': 'file.txt'}])
    path.write_text('changed before approval')
    assert finished(service, service.approve(task['id'], True))['status'] == 'failed'
    assert path.read_text() == 'changed before approval'
    task = finished(service, submit(work, [{'action': 'write', 'path': 'file.txt', 'content': 'ours'}]))
    path.write_text('another editor')
    assert finished(service, service.restore(task['id']))['status'] == 'failed'
    assert path.read_text() == 'another editor'


@pytest.mark.parametrize(
    'path',
    [
        '../outside.txt',
        '/outside.txt',
        'C:/outside.txt',
        '..\\outside.txt',
        'file.txt:stream',
        'CON',
        'a/../b',
        '.git/config',
        '.env',
        'bad.',
    ],
)
def test_path_escape_and_sensitive_names_blocked(work, path):
    with pytest.raises(WorkError):
        submit(work, [{'action': 'write', 'path': path, 'content': 'no'}])


def test_symlink_and_hardlink_cannot_expand_grant(work, tmp_path):
    service, _, folder = work
    outside = tmp_path / 'outside.txt'
    outside.write_bytes(b'outside')
    os.link(outside, folder / 'hard.txt')
    with pytest.raises(WorkError):
        submit(work, [{'action': 'write', 'path': 'hard.txt', 'content': 'no'}])
    assert outside.read_bytes() == b'outside'
    try:
        (folder / 'link').symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        return  # Windows accounts without symlink privileges still run the hardlink assertion.
    with pytest.raises(WorkError):
        submit(work, [{'action': 'write', 'path': 'link/outside.txt', 'content': 'no'}])
    with pytest.raises(WorkError):
        service.grant(str(folder / 'link'))


def test_no_destination_overwrite_and_no_repeated_mutation(work):
    _, _, folder = work
    (folder / 'a.txt').write_bytes(b'a')
    (folder / 'b.txt').write_bytes(b'b')
    with pytest.raises(WorkError):
        submit(work, [{'action': 'move', 'path': 'a.txt', 'destination': 'b.txt'}])
    with pytest.raises(WorkError):
        submit(work, [{'action': 'write', 'path': 'a.txt', 'content': 'x'}, {'action': 'delete', 'path': 'a.txt'}])
    assert (folder / 'b.txt').read_bytes() == b'b'


def test_revoke_blocks_waiting_and_future_tasks_and_keeps_recovery(work):
    service, workspace_id, folder = work
    (folder / 'file.txt').write_bytes(b'old')
    edited = finished(service, submit(work, [{'action': 'write', 'path': 'file.txt', 'content': 'new'}]))
    waiting = submit(work, [{'action': 'delete', 'path': 'file.txt'}])
    service.revoke(workspace_id)
    assert service.task(waiting['id'])['status'] == 'cancelled'
    with pytest.raises(WorkError):
        service.restore(edited['id'])
    with pytest.raises(WorkError):
        submit(work, [{'action': 'list'}])
    assert service.grant(str(folder))['id'] == workspace_id
    assert finished(service, service.restore(edited['id']))['status'] == 'restored'


def test_cancellation_stops_remaining_steps_and_partial_work_can_be_restored(work, monkeypatch):
    service, _, folder = work
    original = service.operate

    def cancel_after_first(root, step):
        result = original(root, step)
        # The event is checked between atomic file operations.
        next(iter(service.jobs.values()))[1].set()
        return result

    monkeypatch.setattr(service, 'operate', cancel_after_first)
    task = finished(
        service,
        submit(
            work,
            [
                {'action': 'write', 'path': 'first.txt', 'content': 'one'},
                {'action': 'write', 'path': 'second.txt', 'content': 'two'},
            ],
        ),
    )
    assert task['status'] == 'cancelled' and task['can_restore']
    assert (folder / 'first.txt').exists() and not (folder / 'second.txt').exists()
    assert finished(service, service.restore(task['id']))['status'] == 'restored'
    assert not (folder / 'first.txt').exists()


def test_restart_does_not_replay_and_prepared_write_can_be_restored(work):
    service, workspace_id, folder = work
    (folder / 'file.txt').write_text('old')
    task = finished(service, submit(work, [{'action': 'write', 'path': 'file.txt', 'content': 'new'}]))
    record = service.task(task['id'])
    record['status'] = 'running'
    record['steps'][0]['state'] = 'prepared'
    service.store.save_file_task(record)
    service.close()
    restarted = FileWork(service.store)
    try:
        assert restarted.task(task['id'])['status'] == 'interrupted'
        assert (folder / 'file.txt').read_text() == 'new'
        assert finished(restarted, restarted.restore(task['id']))['status'] == 'restored'
        assert (folder / 'file.txt').read_text() == 'old'
        # Recovery of a crash after the restore itself is also idempotent.
        record['status'] = 'restoring'
        record['steps'][0]['state'] = 'restoring'
        restarted.store.save_file_task(record)
    finally:
        restarted.close()
    again = FileWork(service.store)
    try:
        assert finished(again, again.restore(task['id']))['status'] == 'restored'
        assert (folder / 'file.txt').read_text() == 'old'
    finally:
        again.close()


def test_read_limit_binary_rejection_and_directory_delete_denied(work):
    service, _, folder = work
    (folder / 'large.txt').write_text('x' * 17000)
    (folder / 'binary').write_bytes(b'\x00\xff')
    task = finished(service, submit(work, [{'action': 'read', 'path': 'large.txt'}]))
    assert len(task['steps'][0]['result']['text']) == 16000
    assert task['steps'][0]['result']['truncated']
    assert finished(service, submit(work, [{'action': 'read', 'path': 'binary'}]))['status'] == 'failed'
    with pytest.raises(WorkError):
        submit(work, [{'action': 'delete', 'path': '.'}])


def test_backup_tampering_stops_restore_without_overwrite(work):
    service, _, folder = work
    path = folder / 'file.txt'
    path.write_bytes(b'original')
    task = finished(service, submit(work, [{'action': 'write', 'path': 'file.txt', 'content': 'edited'}]))
    service.backup_path(task['id'], 0).write_bytes(b'tampered')
    restored = finished(service, service.restore(task['id']))
    assert restored['status'] == 'failed' and '备份校验失败' in restored['error']
    assert path.read_bytes() == b'edited'


def test_replaced_root_needs_new_authorization(work):
    service, _, folder = work
    folder.rename(folder.with_name('original-files'))
    folder.mkdir()
    with pytest.raises(WorkError, match='替换'):
        submit(work, [{'action': 'write', 'path': 'file.txt', 'content': 'no'}])
    assert not (folder / 'file.txt').exists()


def test_large_file_tool_result_stays_valid_json_with_explicit_partial_flag():
    result = {'ok': True, 'task': {'id': 't1', 'steps': [{'result': {'text': '资料' * 16000}}]}}
    text = chat.tool_content(result)
    parsed = json.loads(text)
    assert parsed['truncated'] and parsed['task_id'] == 't1'
    assert len(text) < 16000 and '只是部分预览' in parsed['message']
