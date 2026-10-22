import asyncio
import json
import os
from threading import Event

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk, ToolMessage

from backend.app import config, feature_config, main, runtime
from backend.app.filework import FileTaskRequest, FileWork, WorkError
from backend.app.routes import chat
from backend.app.store import Store
from backend.app.tool_registry import ToolRegistry


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


def test_local_routes_contract_and_lan_denial(work, monkeypatch):
    service, _, folder = work
    monkeypatch.setattr(runtime, 'store', service.store)
    with TestClient(main.app) as client:
        grant = client.post('/api/work/workspaces', json={'path': str(folder)})
        assert grant.status_code == 201 and 'identity' not in grant.json()
        task = client.post('/api/work/tasks', json={'workspace_id': grant.json()['id'], 'steps': [{'action': 'list'}]})
        assert task.status_code == 201
        assert client.get('/api/work/tasks').status_code == 200
        assert (
            client.post(
                '/api/work/tasks', json={'workspace_id': grant.json()['id'], 'steps': [{'action': 'shell'}]}
            ).status_code
            == 422
        )
    from backend.app import access

    monkeypatch.setenv('SHUNGUANG_LAN_MODE', '1')
    monkeypatch.setattr(access, 'authenticated', lambda _: True)
    with TestClient(main.app, client=('192.168.1.9', 12345), base_url='http://127.0.0.1') as remote:
        for url in ('/api/work/workspaces', '/api/work/tasks'):
            assert remote.get(url).status_code == 403


def test_registry_respects_enabled_tools_and_never_allows_model_approval(work):
    service, _, _ = work
    features = feature_config.FeatureConfig()
    context = ({'id': 'm', 'conversation_id': 'c', 'content': 'hello'}, [])
    registry = ToolRegistry(features, service.store, *context, work=service)
    assert {'weather', 'web_search', 'remember_user_fact', 'recall_conversations', 'workspace_files'} == set(
        registry.handlers
    )
    assert not asyncio.run(registry.execute('approve_delete', {'approved': True}))['ok']
    features.tools.weather_enabled = False
    features.memory.auto_save = False
    disabled = ToolRegistry(features, service.store, *context)
    assert 'weather' not in disabled.handlers and 'remember_user_fact' not in disabled.handlers
    assert 'workspace_files' not in disabled.handlers


def test_file_tool_schema_is_compatible_with_existing_provider_conversion(work):
    from langchain_core.utils.function_calling import convert_to_openai_tool

    service, _, _ = work
    registry = ToolRegistry(feature_config.FeatureConfig(), service.store, {}, [], work=service)
    tool = convert_to_openai_tool(registry.definitions[-1])['function']
    step_schema = tool['parameters']['properties']['steps']['items']
    assert tool['name'] == 'workspace_files'
    assert step_schema['properties']['action']['enum'] == ['list', 'read', 'write', 'move', 'delete', 'read_document']


def test_large_file_tool_result_stays_valid_json_with_explicit_partial_flag():
    result = {'ok': True, 'task': {'id': 't1', 'steps': [{'result': {'text': '资料' * 16000}}]}}
    text = chat.tool_content(result)
    parsed = json.loads(text)
    assert parsed['truncated'] and parsed['task_id'] == 't1'
    assert len(text) < 16000 and '只是部分预览' in parsed['message']


def test_chat_dispatches_local_file_task_and_persists_actual_result(work, monkeypatch):
    service, workspace_id, folder = work
    (folder / 'file.txt').write_text('real file text')
    monkeypatch.setattr(runtime, 'store', service.store)
    config.save_config(config.ModelConfig(llm_model='test', llm_api_key='test-key'))
    bound = []

    class Model:
        def bind_tools(self, definitions):
            bound.append({item['name'] for item in definitions})
            return self

        async def astream(self, history):
            if isinstance(history[-1], ToolMessage):
                result = json.loads(history[-1].content)
                assert result['ok'] and result['task']['steps'][0]['result']['text'] == 'real file text'
                yield AIMessageChunk(content='已经读到了文件内容。')
            else:
                yield AIMessageChunk(
                    content='',
                    tool_calls=[
                        {
                            'name': 'workspace_files',
                            'id': 'file1',
                            'args': {'workspace_id': workspace_id, 'steps': [{'action': 'read', 'path': 'file.txt'}]},
                        }
                    ],
                )

    monkeypatch.setattr(chat, 'build_model', lambda _: Model())
    with TestClient(main.app) as client:
        response = client.post('/api/chat', json={'content': '读取授权目录的 file.txt'})
        assert 'event: done' in response.text and 'real file text' in response.text
        assert 'workspace_files' in bound[0]
        assert service.store.list_file_tasks()[0]['origin'] == 'chat'


def test_cancelled_registry_wait_stops_worker_before_acknowledging(work, monkeypatch):
    service, workspace_id, folder = work
    entered, release = Event(), Event()
    original = service.operate

    def slow(root, step):
        entered.set()
        assert release.wait(5)
        return original(root, step)

    monkeypatch.setattr(service, 'operate', slow)
    registry = ToolRegistry(feature_config.FeatureConfig(), service.store, {}, [], work=service)

    async def run():
        running = asyncio.create_task(
            registry.execute(
                'workspace_files',
                {
                    'workspace_id': workspace_id,
                    'steps': [
                        {'action': 'write', 'path': 'first.txt', 'content': 'one'},
                        {'action': 'write', 'path': 'second.txt', 'content': 'two'},
                    ],
                },
            )
        )
        assert await asyncio.to_thread(entered.wait, 5)
        running.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert service.store.list_file_tasks()[0]['status'] == 'cancelled'
        assert not (folder / 'second.txt').exists()

    asyncio.run(run())
