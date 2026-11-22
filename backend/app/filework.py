"""Local file tasks: explicit grants, bounded operations and a durable undo journal.

This is a file API, not a process sandbox. It never executes file contents.
"""

import asyncio
import hashlib
import os
import stat
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, RLock

from . import config
from .file_paths import PathAccess, local_request, move_exclusive, no_link
from .work_cues import WorkCues
from .work_models import (
    BLOCKED,
    MAX_FILE_BYTES,
    MAX_TEXT_CHARS,
    TERMINAL,
    FileStep,
    FileTaskRequest,
    TaskCancelled,
    WorkError,
    WorkPause,
)

__all__ = [
    'MAX_FILE_BYTES',
    'MAX_TEXT_CHARS',
    'TERMINAL',
    'BLOCKED',
    'WorkError',
    'TaskCancelled',
    'WorkPause',
    'FileStep',
    'FileTaskRequest',
    'local_request',
    'no_link',
    'move_exclusive',
    'FileWork',
    'public_task',
    'summary_retryable',
]


def summary_retryable(record):
    reads = [step for step in record['steps'] if step['action'] == 'read_document']
    summaries = [step for step in record['steps'] if step['action'] == 'summarize']
    return bool(
        record['status'] == 'failed'
        and record.get('context', {}).get('stage') == 'summarizing'
        and reads
        and len(summaries) == 1
        and len(reads) + 1 == len(record['steps'])
        and all(step['state'] == 'complete' and step.get('result') and step.get('read_stamp') for step in reads)
        and summaries[0]['state'] != 'complete'
        and not summaries[0].get('result')
    )


def vision_retryable(record):
    context = record.get('context', {})
    return (
        record['status'] == 'failed'
        and record.get('origin') == 'chat'
        and context.get('stage') == 'recognizing'
        and not context.get('save_result', True)
        and any(
            step['action'] == 'read_document' and step.get('read_stamp') and step['state'] != 'complete'
            for step in record['steps']
        )
    )


def public_task(record):
    return {
        **record,
        'can_retry_summary': summary_retryable(record),
        'can_retry_vision': vision_retryable(record),
        'steps': [
            {
                key: value
                for key, value in step.items()
                if key
                not in (
                    'content',
                    'before',
                    'after',
                    'backup',
                    'read_stamp',
                    'recognized',
                    'vision_approval',
                    'vision_declined',
                    'current_result',
                    'cursor',
                    'notes',
                )
            }
            for step in record['steps']
        ],
        'can_restore': record['status'] in TERMINAL - {'restored'}
        and any(step['state'] in ('prepared', 'applied', 'restoring') for step in record['steps']),
    }


class FileWork(PathAccess):
    def __init__(self, store):
        self.store = store
        self.gate = RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='file-work')
        self.jobs = {}
        self.closed = False
        self.output_root = config.DATA_DIR.absolute() / 'outputs'
        self.upload_root = (store.path.parent / 'attachments').resolve()
        self.cues = WorkCues(store)
        from .conversation_cleanup import recover

        recover(self)
        store.interrupt_file_tasks()
        self.retire_legacy_tasks()

    def close(self):
        with self.gate:
            self.closed = True
            for _, stop in self.jobs.values():
                stop.set()
        self.pool.shutdown(wait=True)
        self.cues.close()

    def revoke(self, workspace_id):
        with self.gate:
            if not self.store.revoke_workspace(workspace_id):
                raise WorkError('工作文件夹不存在。', 404)
            for task_id, (_, stop) in self.jobs.items():
                if self.store.get_file_task(task_id)['workspace_id'] == workspace_id:
                    stop.set()
            for task in self.store.list_file_tasks(10000):
                if task['workspace_id'] == workspace_id and task['status'] in (
                    'waiting_approval',
                    'waiting_vision',
                    'waiting_limit',
                    'waiting_output',
                ):
                    task.update(status='cancelled', error='已撤销文件夹授权。')
                    self.store.save_file_task(task)
                    self.cues.emit(task, 'cancelled')

    def task(self, task_id):
        record = self.store.get_file_task(task_id)
        if record is None:
            raise WorkError('任务不存在。', 404)
        return record

    def read_only_task(self, task):
        workspace = self.store.get_workspace(task['workspace_id'])
        return (
            bool(workspace)
            and Path(workspace['path']) == self.upload_root
            and not task['context'].get('save_result', True)
            and all(
                step['action'] in ('read_document', 'summarize')
                and step.get('workspace_id', task['workspace_id']) == task['workspace_id']
                for step in task['steps']
            )
        )

    def retire_legacy_tasks(self):
        with self.store.connect() as db:
            waiting = [
                row['id']
                for row in db.execute(
                    "SELECT id FROM file_tasks WHERE status IN ('waiting_approval','waiting_vision','waiting_limit','waiting_output')"
                )
            ]
        for identity in waiting:
            task = self.task(identity)
            if not self.read_only_task(task) or task['status'] in ('waiting_approval', 'waiting_output'):
                task.update(status='interrupted', error='旧版办公任务已停用，历史文件仍保留。')
                self.store.save_file_task(task)

    def submit(self, payload, origin='workbench', conversation_id=None, model_choice=None, source_message_id=None):
        with self.gate:
            if (
                origin == 'chat'
                and not payload.instruction
                and any(step.action == 'read_document' for step in payload.steps)
            ):
                message = (
                    next(
                        (
                            item
                            for item in self.store.messages(conversation_id)
                            if item['id'] == source_message_id and item['role'] == 'user'
                        ),
                        {},
                    )
                    if conversation_id
                    else {}
                )
                payload = payload.model_copy(
                    update={'instruction': message.get('content', '')[:4000] or '请简要说明资料的主要内容。'}
                )
            self.jobs = {key: job for key, job in self.jobs.items() if not job[0].done()}
            if self.closed or len(self.jobs) >= 8:
                raise WorkError('文件任务队列已满或正在停止，请稍后重试。', 429)
            root = self.root(payload.workspace_id)
            steps, touched = [], set()
            for operation in payload.steps:
                step = operation.model_dump(exclude_none=True)
                source = self.path(root, operation.path)
                step.update(state='pending', before={}, after={})
                if operation.action in ('write', 'move', 'delete'):
                    if source == root:
                        raise WorkError('不能修改工作文件夹本身。', 403)
                    paths = [operation.path]
                    before = self.fingerprint(source)
                    if operation.action != 'write' and before is None:
                        raise WorkError('要移动或删除的文件不存在。', 404)
                    if not source.parent.is_dir():
                        raise WorkError('请先使用已有的目标文件夹。', 422)
                    step['before'][operation.path] = before
                    if operation.action == 'write':
                        data = operation.content.encode('utf-8')
                        step['after'][operation.path] = {
                            'sha256': hashlib.sha256(data).hexdigest(),
                            'bytes': len(data),
                            'mode': before['mode'] if before else (0o666 if os.name == 'nt' else 0o600),
                        }
                    elif operation.action == 'delete':
                        step['after'][operation.path] = None
                    else:
                        dest = self.path(root, operation.destination)
                        if dest == root or not dest.parent.is_dir() or dest.exists():
                            raise WorkError('移动目标已存在或目标文件夹不可用，不会覆盖目标。')
                        paths.append(operation.destination)
                        step['before'][operation.destination] = None
                        step['after'].update({operation.path: None, operation.destination: before})
                    keys = {os.path.normcase(str(self.path(root, item))) for item in paths}
                    if len(keys) != len(paths) or touched & keys:
                        raise WorkError('同一任务不能多次修改同一路径；请拆分任务，避免改名循环或覆盖。', 422)
                    touched.update(keys)
                steps.append(step)
            if payload.instruction:
                steps.append(
                    {
                        'action': 'summarize',
                        'path': '.',
                        'instruction': payload.instruction,
                        'state': 'pending',
                        'before': {},
                        'after': {},
                    }
                )
            status = 'waiting_approval' if any(step.action == 'delete' for step in payload.steps) else 'queued'
            task = self.store.create_file_task(
                payload.workspace_id, payload.title, steps, status, origin, conversation_id
            )
            task['context'].update(
                save_result=payload.save_result,
                source_message_id=source_message_id,
                chat_reply=origin == 'chat' and bool(payload.instruction),
            )
            if source_message_id and conversation_id:
                message = next(
                    (item for item in self.store.messages(conversation_id) if item['id'] == source_message_id), {}
                )
                task['context']['sources'] = [
                    {'kind': 'attachment', 'id': item['id'], 'name': item['name']}
                    for item in message.get('attachments', [])
                    if item.get('workspace_id') == payload.workspace_id
                    and any(step.path == item.get('path') for step in payload.steps)
                ]
            self.store.save_file_task(task)
            if payload.instruction or any(step.action == 'read_document' for step in payload.steps):
                from .model_choices import default_choice

                choice = (
                    model_choice
                    or (self.store.conversation_model(conversation_id) if conversation_id else None)
                    or default_choice()
                )
                if choice.get('model'):
                    task['context']['model_choice'] = dict(choice)
                    self.store.save_file_task(task)
            if status == 'queued':
                self.schedule(task['id'])
            return public_task(task)

    def schedule(self, task_id, restore=False):
        if self.closed:
            raise WorkError('服务正在停止，请稍后重试。', 503)
        stop = Event()
        # One worker serializes this application's writes. External programs are
        # checked by fingerprints; this does not lock other applications out.
        future = self.pool.submit(self.run, task_id, stop, restore)
        self.jobs[task_id] = future, stop

    def approve(self, task_id, approved):
        with self.gate:
            task = self.task(task_id)
            if task['status'] != 'waiting_approval':
                raise WorkError('任务已经处理，不能重复授权或更改授权参数。')
            self.root(task['workspace_id'])
            task.update(status='queued' if approved else 'cancelled', error='' if approved else '用户拒绝了删除授权。')
            self.store.save_file_task(task)
            if approved:
                self.schedule(task_id)
            return public_task(task)

    def cancel(self, task_id):
        job = self.jobs.get(task_id)
        if job and not job[0].done():
            # Signal without taking the file-operation gate: the worker may be
            # finishing an OS operation while the caller waits for cancellation.
            job[1].set()
            if not job[0].cancel():
                return public_task(self.task(task_id))
        with self.gate:
            task = self.task(task_id)
            if task['status'] in ('queued', 'waiting_approval', 'waiting_vision', 'waiting_limit', 'waiting_output'):
                task.update(status='cancelled', error='用户取消了任务。')
                self.store.save_file_task(task)
                self.cues.emit(task, 'cancelled')
            return public_task(task)

    def upload(self, name, data):
        from uuid import uuid4

        if not data or len(data) > MAX_FILE_BYTES or Path(name).name != name or '/' in name or '\\' in name:
            raise WorkError('上传文件名无效、为空或超过 20 MiB。', 422)
        with self.gate:
            self.upload_root.mkdir(parents=True, exist_ok=True)
            workspace = self.grant(str(self.upload_root))
            root = self.root(workspace['id'])
            self.path(root, name)
            original_name = name
            name = uuid4().hex[:10] + '-' + name
            path = self.path(root, name)
            stamp = {
                'sha256': hashlib.sha256(data).hexdigest(),
                'bytes': len(data),
                'mode': 0o666 if os.name == 'nt' else 0o600,
            }
            step = {
                'action': 'upload',
                'path': name,
                'state': 'prepared',
                'before': {name: None},
                'after': {name: stamp},
                'result': {'message': '已保存上传副本；原文件未修改。', 'name': original_name},
            }
            task = self.store.create_file_task(workspace['id'], '上传文件', [step], 'running')
            try:
                self.put(path, data, None)
                step['state'] = 'applied'
                task['status'] = 'complete'
            except OSError:
                task.update(status='failed', error='上传文件保存失败。')
                raise
            finally:
                self.store.save_file_task(task)
            return {'workspace': workspace, 'path': name, 'task': public_task(task)}

    def retry_summary(self, task_id, extend_timeout=False):
        return self.retry_read_task(task_id, vision=False, extend_timeout=extend_timeout)

    def retry_read_task(self, task_id, *, vision, extend_timeout=False):
        self.settle_pause(task_id)
        with self.gate:
            task = self.task(task_id)
            if vision and not (vision_retryable(task) and self.read_only_task(task)):
                raise WorkError('当前任务无法重新识图。')
            if not vision and not summary_retryable(task):
                raise WorkError('当前任务没有可重试的未完成总结。')
            from .document_tasks import task_model

            value = task_model(task)
            if not config.public_config(value)['configured']:
                raise WorkError('请先恢复原任务使用的模型连接。', 422)
            for step in task['steps']:
                if step['action'] == 'read_document' and step.get('read_stamp'):
                    root = self.root(step.get('workspace_id', task['workspace_id']))
                    self.check_state(root, {step['path']: step['read_stamp']})
            if self.closed or sum(not job[0].done() for job in self.jobs.values()) >= 8:
                raise WorkError('文件任务队列已满或正在停止，请稍后重试。', 429)
            if extend_timeout:
                task['context']['summary_timeout'] = 120
            else:
                task['context'].pop('summary_timeout', None)
            if task.get('origin') == 'chat':
                if not task['context'].get('chat_reply'):
                    task['context']['save_result'] = False
                task['context']['chat_reply'] = True
            task.update(status='queued', error='')
            self.store.save_file_task(task)
            self.schedule(task_id)
            return public_task(task)

    def continue_task(self, task_id, approved):
        self.settle_pause(task_id)
        with self.gate:
            task = self.task(task_id)
            if task['status'] not in ('waiting_limit', 'waiting_output'):
                raise WorkError('任务当前不在等待继续状态。')
            if not approved:
                return self.cancel(task_id)
            if task['status'] == 'waiting_output':
                from .work_artifacts import output_root

                output_root(self)
            if task['context'].get('pause', {}).get('kind') == 'overwrite':
                task['context']['overwrite_approved'] = True
            task['context'].pop('pause', None)
            task['context']['budget'] = {}
            task.update(status='queued', error='')
            self.store.save_file_task(task)
            self.schedule(task_id)
            return public_task(task)

    def approve_vision(self, task_id, approved, profile_id='', expected_signature=''):
        from . import document_models

        self.settle_pause(task_id)
        with self.gate:
            task = self.task(task_id)
            if task['status'] != 'waiting_vision':
                raise WorkError('任务已处理，不能重复授权。')
            step = next(item for item in task['steps'] if item['state'] == 'waiting_vision')
            if approved:
                root = self.root(step.get('workspace_id', task['workspace_id']))
                self.check_state(root, {step['path']: step['read_stamp']})
                if document_models.selected(profile_id, expected_signature) is None:
                    raise WorkError('请选择已确认支持视觉的模型；配置变化时需要重新核对授权卡。', 422)
                step['vision_approval'] = {'profile_id': profile_id, 'signature': expected_signature}
                step['state'] = 'pending'
            else:
                step['vision_declined'] = True
                step['state'] = 'complete' if step.get('scope', 'range') == 'range' else 'pending'
                step['vision_request'] = None
                step['result']['warnings'].append('用户拒绝了替代识别；已读取的内容保留，未识别图像不作为总结依据。')
            task.update(status='queued', error='')
            self.store.save_file_task(task)
            self.schedule(task_id)
            return public_task(task)

    def restore(self, task_id):
        with self.gate:
            task = self.task(task_id)
            if not public_task(task)['can_restore']:
                raise WorkError('任务仍在执行，或没有需要恢复的修改。')
            self.root(task['workspace_id'])
            task.update(status='restoring', error='')
            self.store.save_file_task(task)
            self.schedule(task_id, restore=True)
            return public_task(task)

    async def wait(self, task_id):
        job = self.jobs.get(task_id)
        if job and not job[0].cancelled():
            future = asyncio.wrap_future(job[0])
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                self.cancel(task_id)
                await asyncio.shield(future)
                raise
        return public_task(self.task(task_id))

    def settle_pause(self, task_id):
        job = self.jobs.get(task_id)
        if (
            job
            and not job[0].done()
            and self.task(task_id)['status'] in ('waiting_vision', 'waiting_limit', 'waiting_output', 'failed')
        ):
            try:
                job[0].result(timeout=10)
            except TimeoutError:
                raise WorkError('任务正在保存暂停记录，请稍后重试。')

    def checkpoint(self, stop, deadline):
        if stop.is_set():
            raise TaskCancelled()
        if time.monotonic() > deadline:
            raise WorkError('文件任务超时，已在安全步骤边界停止。')

    def check_state(self, root, expected):
        if any(self.fingerprint(self.path(root, name)) != stamp for name, stamp in expected.items()):
            raise WorkError('文件内容、权限或目标位置已发生变化，已停止，避免覆盖其他修改。')

    def backup_path(self, task_id, index):
        return self.store.path.parent / 'file-backups' / task_id / f'{index}.bin'

    def save_backup(self, task, index, root, step):
        original = step['before'].get(step['path'])
        if original is None:
            return
        path = self.backup_path(task['id'], index)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.path(root, step['path']).read_bytes()
        if len(data) != original['bytes'] or hashlib.sha256(data).hexdigest() != original['sha256']:
            raise WorkError('备份期间源文件发生变化，尚未修改文件。')
        with path.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        step['backup'] = True

    def put(self, path, data, expected, mode=None):
        if self.fingerprint(path) != expected:
            raise WorkError('写入前文件已变化，已停止。')
        descriptor, temporary = tempfile.mkstemp(prefix='.shunguang-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if mode is not None or expected:
                os.chmod(temporary, mode if mode is not None else expected['mode'])
            if self.fingerprint(path) != expected:
                raise WorkError('保存前文件已变化，已停止。')
            if expected is None:
                move_exclusive(temporary, path)
            else:
                os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def operate(self, root, step):
        path = self.path(root, step['path'])
        action = step['action']
        if action == 'list':
            if not path.is_dir():
                raise WorkError('要列出的路径不是文件夹。', 422)
            entries = []
            with os.scandir(path) as iterator:
                for entry in iterator:
                    if len(entries) >= 200:
                        return {'entries': entries, 'truncated': True}
                    try:
                        target = self.path(root, str(Path(entry.path).relative_to(root)))
                        value = no_link(target)
                        entries.append(
                            {'name': entry.name, 'directory': stat.S_ISDIR(value.st_mode), 'bytes': value.st_size}
                        )
                    except WorkError:
                        continue
            return {'entries': entries, 'truncated': False}
        if action == 'read':
            stamp = self.fingerprint(path)
            if stamp is None:
                raise WorkError('要读取的文件不存在。', 404)
            try:
                with path.open('r', encoding='utf-8-sig') as stream:
                    text = stream.read(MAX_TEXT_CHARS + 1)
            except UnicodeError:
                raise WorkError('基础阅读仅支持 UTF-8 文本；办公文档和图片阅读将在后续版本接入。', 422)
            if '\x00' in text:
                raise WorkError('此文件不是可直接读取的文本。', 422)
            self.check_state(root, {step['path']: stamp})
            return {'text': text[:MAX_TEXT_CHARS], 'truncated': len(text) > MAX_TEXT_CHARS}
        if action == 'write':
            self.put(path, step['content'].encode('utf-8'), step['before'][step['path']])
        elif action == 'move':
            destination = self.path(root, step['destination'])
            move_exclusive(path, destination)
        elif action == 'delete':
            path.unlink()
        return {'message': '文件操作已完成。'}

    def undo(self, task, index, root, step):
        # The prepared journal also covers a crash between an OS write and the
        # following DB update. Matching the old state makes recovery idempotent.
        actual = {name: self.fingerprint(self.path(root, name)) for name in step['before']}
        if actual == step['before']:
            step['state'] = 'restored'
            self.store.save_file_task(task)
            return
        self.check_state(root, step['after'])
        path = self.path(root, step['path'])
        data = None
        if step['before'][step['path']] is not None:
            backup = self.backup_path(task['id'], index)
            no_link(backup)
            data = backup.read_bytes()
            expected = step['before'][step['path']]
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise WorkError('备份校验失败，未覆盖当前文件。')
        step['state'] = 'restoring'
        self.store.save_file_task(task)
        if step['action'] == 'move':
            destination = self.path(root, step['destination'])
            move_exclusive(destination, path)
        elif data is None:
            path.unlink()
        else:
            self.put(path, data, step['after'][step['path']], mode=step['before'][step['path']]['mode'])
        step['state'] = 'restored'
        self.store.save_file_task(task)

    def run(self, task_id, stop, restore):
        task = self.task(task_id)
        document_task = any(step['action'] in ('read_document', 'summarize', 'office') for step in task['steps'])
        deadline = time.monotonic() + (1800 if document_task else 60)

        def check():
            return self.checkpoint(stop, deadline)

        try:
            with self.gate:
                self.checkpoint(stop, deadline)
                self.root(task['workspace_id'])
                task.update(status='restoring' if restore else 'running', error='')
                self.store.save_file_task(task)
                if not restore:
                    self.cues.emit(
                        task, 'start' if all(item['state'] == 'pending' for item in task['steps']) else 'progress'
                    )
            indexes = range(len(task['steps']) - 1, -1, -1) if restore else range(len(task['steps']))
            for index in indexes:
                step = task['steps'][index]
                if not restore and step['state'] in ('applied', 'complete'):
                    continue
                if not restore and step['action'] == 'office':
                    from . import office_tasks

                    check()
                    if not office_tasks.run(self, task, step, check):
                        return
                    step['state'] = 'complete'
                    self.store.save_file_task(task)
                    continue
                if not restore and step['action'] in ('read_document', 'summarize'):
                    from . import document_tasks

                    check()
                    self.root(task['workspace_id'])
                    if step['action'] == 'read_document':
                        reader = (
                            document_tasks.read if step.get('scope', 'range') == 'range' else document_tasks.read_all
                        )
                        if not reader(self, task, step, check):
                            return
                    else:
                        with self.gate:
                            for read_step in task['steps']:
                                if read_step['action'] == 'read_document':
                                    root = self.root(read_step.get('workspace_id', task['workspace_id']))
                                    self.check_state(root, {read_step['path']: read_step.get('read_stamp')})
                        document_tasks.summarize(self, task, step, check)
                    step['state'] = 'complete'
                    self.store.save_file_task(task)
                    continue
                with self.gate:
                    self.checkpoint(stop, deadline)
                    root = self.root(step.get('workspace_id', task['workspace_id']))
                    step = task['steps'][index]
                    if restore:
                        if step['state'] in ('prepared', 'applied', 'restoring'):
                            self.undo(task, index, root, step)
                        continue
                    self.check_state(root, step['before'])
                    if step['before']:
                        self.save_backup(task, index, root, step)
                        step['state'] = 'prepared'
                        self.store.save_file_task(task)
                        self.check_state(root, step['before'])
                        self.checkpoint(stop, deadline)
                    step['result'] = self.operate(root, step)
                    step['state'] = 'applied' if step['before'] else 'complete'
                    self.store.save_file_task(task)
            if (
                not restore
                and task['context'].get('save_result', True)
                and any(item['action'] == 'summarize' for item in task['steps'])
            ):
                from .work_artifacts import save_summary

                check()
                if not save_summary(self, task):
                    return
            task['status'] = 'restored' if restore else 'complete'
        except WorkPause:
            task['status'] = 'waiting_limit'
        except TaskCancelled:
            task.update(status='cancelled', error='任务已取消，已完成的修改可在记录中检查并恢复。')
        except WorkError as error:
            task.update(status='failed', error=error.message)
        except OSError as error:
            from .logging_setup import report_error

            phase = task.get('context', {}).get('stage')
            phase = phase if phase in ('reading', 'recognizing', 'summarizing', 'saving') else 'file_operation'
            report_error('file_task_io_' + phase, error)
            task.update(status='failed', error='文件暂时无法访问或写入，本次处理已停止。')
        except Exception as error:
            from .logging_setup import report_error

            report_error('file_task', error)
            task.update(status='failed', error='任务未能完成，已读取的资料保留在记录中；请检查文档格式和模型配置。')
        finally:
            with self.gate:
                if stop.is_set() and task['status'] not in TERMINAL:
                    task.update(status='cancelled', error='任务已取消，已完成部分保留在记录中。')
                self.store.save_file_task(task)
                if task['status'] in ('waiting_limit', 'waiting_output'):
                    self.cues.emit(task, task['status'])
                if task['status'] in ('complete', 'failed', 'cancelled', 'restored'):
                    kind = task['status']
                    if kind == 'complete' and any(item.get('result', {}).get('partial') for item in task['steps']):
                        kind = 'partial'
                    self.cues.emit(task, kind)
