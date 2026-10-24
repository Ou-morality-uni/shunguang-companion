"""Local file tasks: explicit grants, bounded operations and a durable undo journal.

This is a file API, not a process sandbox. It never executes file contents.
"""

import asyncio
import ctypes
import hashlib
import os
import stat
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PureWindowsPath
from threading import Event, RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import config
from .work_cues import WorkCues

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 16000
TERMINAL = {'complete', 'failed', 'cancelled', 'interrupted', 'restored'}
BLOCKED = {'.git', '.codex', '.agents', '.aws', '.ssh', '.venv', '.venv-rag', 'node_modules'}


class WorkError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


class TaskCancelled(Exception):
    pass


class WorkPause(Exception):
    pass


class FileStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['list', 'read', 'write', 'move', 'delete', 'read_document']
    path: str = Field(default='.', min_length=1, max_length=500)
    destination: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, max_length=200000)
    start: int = Field(default=1, ge=1, le=1000000)
    limit: int = Field(default=20, ge=1, le=50)
    visual: bool = False
    scope: Literal['range', 'full', 'focused'] = 'range'
    query: str = Field(default='', max_length=300)

    @model_validator(mode='after')
    def operation_fields(self):
        if (self.action == 'move') != (self.destination is not None):
            raise ValueError('只有移动操作需要目标路径')
        if (self.action == 'write') != (self.content is not None):
            raise ValueError('只有写入操作需要完整文本内容')
        return self


class FileTaskRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workspace_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default='文件任务', min_length=1, max_length=120)
    steps: list[FileStep] = Field(min_length=1, max_length=50)
    instruction: str = Field(default='', max_length=4000)

    @model_validator(mode='after')
    def bounded_content(self):
        if sum(len(step.content or '') for step in self.steps) > 1000000:
            raise ValueError('任务文本总量过大')
        if self.instruction and not any(step.action == 'read_document' for step in self.steps):
            raise ValueError('阅读要求需要至少一个文档阅读步骤')
        return self


def local_request(request):
    """Never trust Forwarded headers or a LAN login as local file authorization."""
    if request is None or request.client is None:
        return False
    import ipaddress

    peer = request.client.host
    if peer == 'testclient' and request.url.hostname == 'testserver':
        return True
    try:
        return ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return False


def no_link(path):
    value = path.lstat()
    if stat.S_ISLNK(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400:
        raise WorkError('不允许通过符号链接、目录联接或重解析点访问文件。', 403)
    if stat.S_ISREG(value.st_mode) and value.st_nlink != 1:
        raise WorkError('不允许操作存在硬链接的文件。', 403)
    return value


def move_exclusive(source, destination):
    """Atomic move that cannot overwrite another program's new destination."""
    if os.name == 'nt':
        os.rename(source, destination)
    elif sys.platform.startswith('linux'):
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, 'renameat2', None)
        if rename is None:
            raise WorkError('当前系统不支持安全的不覆盖移动。', 422)
        if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
            raise OSError(ctypes.get_errno(), 'exclusive move failed')
    else:
        raise WorkError('当前系统不支持安全的不覆盖移动。', 422)


def public_task(record):
    return {
        **record,
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


class FileWork:
    def __init__(self, store):
        self.store = store
        self.gate = RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='file-work')
        self.jobs = {}
        self.closed = False
        self.output_root = config.DATA_DIR.absolute() / 'outputs'
        self.upload_root = (store.path.parent / 'attachments').resolve()
        self.cues = WorkCues(store)
        store.interrupt_file_tasks()

    def close(self):
        with self.gate:
            self.closed = True
            for _, stop in self.jobs.values():
                stop.set()
        self.pool.shutdown(wait=True)
        self.cues.close()

    def protected(self, path):
        if path == self.upload_root or self.upload_root in path.parents:
            return
        if path == self.output_root or self.output_root in path.parents:
            return
        protected = [config.DATA_DIR.resolve(), config.ROOT / '.git', config.ROOT / '.codex']
        if any(path == item or item in path.parents for item in protected):
            raise WorkError('应用数据、凭据和内部管理目录不属于工作文件范围。', 403)

    def default_output_workspace(self):
        with self.gate:
            for parent in self.output_root.parents:
                no_link(parent)
            self.output_root.mkdir(exist_ok=True)
            no_link(self.output_root)
            existing = next(
                (item for item in self.store.list_workspaces() if Path(item['path']) == self.output_root), None
            )
            if existing:
                self.root(existing['id'])
                workspace = existing
            else:
                workspace = self.grant(str(self.output_root))
            self.store.set_output_workspace(workspace['id'])
            return workspace

    def grant(self, raw_path):
        path = Path(raw_path.strip())
        if not path.is_absolute() or str(path).startswith(('\\\\', '//')) or path == Path(path.anchor):
            raise WorkError('请选择本机已有的具体文件夹，不能授权整个磁盘或网络共享。', 422)
        for part in (path, *path.parents):
            no_link(part)
        path = path.resolve(strict=True)
        if not path.is_dir():
            raise WorkError('工作路径必须是已有文件夹。', 422)
        self.protected(path)
        if any(part.casefold() in BLOCKED or part.casefold().startswith('.env') for part in path.parts):
            raise WorkError('不能授权凭据或内部管理目录。', 403)
        value = no_link(path)
        with self.gate:
            return self.store.grant_workspace(str(path), f'{value.st_dev}:{value.st_ino}')

    def root(self, workspace_id):
        workspace = self.store.get_workspace(workspace_id)
        if not workspace or not workspace['enabled']:
            raise WorkError('工作文件夹尚未授权或已撤销授权。', 403)
        path = Path(workspace['path'])
        for part in (path, *path.parents):
            no_link(part)
        value = no_link(path)
        if not stat.S_ISDIR(value.st_mode) or workspace['identity'] != f'{value.st_dev}:{value.st_ino}':
            raise WorkError('工作文件夹已被替换，请重新授权。', 403)
        self.protected(path)
        return path

    def path(self, root, relative):
        # Apply Windows rules on every platform, including ADS and device names.
        relative = relative.replace('\\', '/')
        if relative == '.':
            return root
        parts = relative.split('/')
        if PureWindowsPath(relative).is_absolute() or PureWindowsPath(relative).drive:
            raise WorkError('文件路径必须相对于授权文件夹。', 403)
        for part in parts:
            if (
                part in ('', '.', '..')
                or part.rstrip(' .') != part
                or any(char in part for char in ':<>"|?*')
                or any(ord(char) < 32 for char in part)
                or PureWindowsPath(part).is_reserved()
                or part.casefold() in BLOCKED
                or part.casefold().startswith(('.env', '.shunguang-'))
            ):
                raise WorkError('路径包含越界、保留名称或受保护的内容。', 403)
        target = root
        root_device = root.stat().st_dev
        for part in parts:
            target = target / part
            self.protected(target)
            if target.exists() or target.is_symlink():
                value = no_link(target)
                if value.st_dev != root_device:
                    raise WorkError('不能通过挂载目录扩大工作范围。', 403)
        if not target.resolve(strict=False).is_relative_to(root):
            raise WorkError('文件路径超出授权范围。', 403)
        return target

    def fingerprint(self, path):
        if not path.exists():
            if path.is_symlink():
                no_link(path)
            return None
        value = no_link(path)
        if not stat.S_ISREG(value.st_mode):
            raise WorkError('此操作仅支持普通文件，不能修改或删除整个目录。', 422)
        if value.st_size > MAX_FILE_BYTES:
            raise WorkError('基础文件任务每个文件最多支持 20 MiB。', 422)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        after = no_link(path)
        if (value.st_ino, value.st_mtime_ns, value.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
            raise WorkError('文件正在被其他程序修改，请稍后重试。')
        return {'sha256': digest.hexdigest(), 'bytes': value.st_size, 'mode': stat.S_IMODE(value.st_mode)}

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

    def submit(self, payload, origin='workbench', conversation_id=None, model_choice=None):
        with self.gate:
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
            and self.task(task_id)['status'] in ('waiting_vision', 'waiting_limit', 'waiting_output')
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
            if not restore and any(item['action'] == 'summarize' for item in task['steps']):
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
        except OSError:
            task.update(
                status='failed', error='文件操作失败，请检查文件占用、磁盘空间和访问权限；已保存的修改可尝试恢复。'
            )
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
