"""Explicit Office overwrite uses the same fingerprint and recovery journal as file tasks."""

import hashlib

from pydantic import BaseModel, ConfigDict, Field

from .filework import WorkError


class OverwriteTarget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workspace_id: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=500)
    version: str = Field(pattern=r'^[0-9a-f]{64}$')


def prepare(work, target, suffix):
    root = work.root(target.workspace_id)
    path = work.path(root, target.path)
    stamp = work.fingerprint(path)
    if not stamp or stamp['sha256'] != target.version or path.suffix.lower() != '.' + suffix:
        raise WorkError('覆盖目标不存在、版本已变化或格式不匹配，请重新核对。')
    return stamp


def commit(work, task, payload, data, check):
    target = payload.overwrite
    if target is None or task['context'].get('overwrite_done'):
        return True
    if not task['context'].get('overwrite_approved'):
        path = work.path(work.root(target.workspace_id), target.path)
        task['context']['pause'] = {
            'kind': 'overwrite',
            'reason': f'新副本已保存。将覆盖 {path}；确认后保留恢复备份再写入。',
        }
        task['status'] = 'waiting_limit'
        return False
    with work.gate:
        check()
        root = work.root(target.workspace_id)
        path = work.path(root, target.path)
        before = task['context']['overwrite_before']
        work.check_state(root, {target.path: before})
        journal = {
            'action': 'office',
            'path': target.path,
            'workspace_id': target.workspace_id,
            'state': 'pending',
            'before': {target.path: before},
            'after': {
                target.path: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'mode': before['mode']}
            },
        }
        index = len(task['steps'])
        task['steps'].append(journal)
        work.store.save_file_task(task)
        work.save_backup(task, index, root, journal)
        journal['state'] = 'prepared'
        work.store.save_file_task(task)
        check()
        work.check_state(root, journal['before'])
        work.put(path, data, before, mode=before['mode'])
        journal['state'] = 'applied'
        task['context']['overwrite_done'] = True
        work.store.save_file_task(task)
    return True
