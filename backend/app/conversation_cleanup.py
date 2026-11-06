"""Journaled removal of exclusive application-managed copies, never source folders."""

import json
import os
from pathlib import Path
from uuid import uuid4

from .filework import TERMINAL, WorkError, move_exclusive, no_link


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def references(values, identity):
    return any(value == identity or value.startswith(identity + '~') for value in values)


def managed_path(work, raw):
    path = Path(raw).absolute()
    for root in (work.upload_root, work.output_root):
        if path != root and path.is_relative_to(root):
            for parent in (root, *root.parents):
                no_link(parent)
            return work.path(root, path.relative_to(root).as_posix())
    raise WorkError('清理路径不在应用管理的附件或成果目录内。', 403)


def finish(work, directory, plan):
    committed = work.store.get_conversation(plan['conversation']) is None
    for item in plan['files']:
        original = managed_path(work, item['original'])
        staged = directory / item['staged']
        if staged.parent != directory or Path(item['staged']).name != item['staged']:
            raise WorkError('删除恢复记录的路径无效。', 403)
        if staged.exists():
            no_link(staged)
            if committed:
                staged.unlink()
            else:
                move_exclusive(staged, original)
    if committed:
        for raw in plan.get('directories', []):
            path = managed_path(work, raw)
            if path.exists():
                no_link(path)
                try:
                    path.rmdir()  # Never remove unknown files recursively.
                except OSError:
                    pass
    (directory / 'plan.json').unlink()
    directory.rmdir()


def recover(work):
    root = work.store.path.parent / 'deletion-journal'
    if not root.exists():
        return
    no_link(root)
    with work.gate:
        for path in root.glob('*/plan.json'):
            no_link(path.parent)
            no_link(path)
            finish(work, path.parent, json.loads(path.read_text(encoding='utf-8')))


def delete(work, conversation_id):
    store = work.store
    with work.gate:
        recover(work)
        if not store.get_conversation(conversation_id):
            return False
        with store.connect() as db:
            tasks = {
                row['id']: {
                    **dict(row),
                    'steps': json.loads(row['steps'] or '[]') or [],
                    'context': json.loads(row['context'] or '{}') or {},
                }
                for row in db.execute('SELECT * FROM file_tasks')
            }
            messages = [
                (row['conversation_id'], list(strings(json.loads(row['metadata'] or '{}'))))
                for row in db.execute('SELECT conversation_id,metadata FROM messages')
            ]
            other_refs = [value for cid, values in messages if cid != conversation_id for value in values]
            other_refs += [
                value
                for row in db.execute(
                    'SELECT payload FROM annotations WHERE conversation_id IS NULL OR conversation_id<>?',
                    (conversation_id,),
                )
                for value in strings(json.loads(row['payload']))
            ]
        owned = {key for key, task in tasks.items() if task.get('conversation_id') == conversation_id}
        if any(tasks[key]['status'] not in TERMINAL for key in owned):
            raise WorkError('这段对话仍有未结束的文件任务，请先完成或取消任务再删除。')
        own_refs = [value for cid, values in messages if cid == conversation_id for value in values]
        candidates = owned | {key for key in tasks if references(own_refs, key)}
        # A retained task may depend on a candidate's upload or output. Propagate protection.
        retained = set(tasks) - candidates
        while True:
            refs = other_refs + [value for key in retained for value in strings(tasks[key])]
            shared = {key for key in candidates if references(refs, key)}
            if not shared:
                break
            candidates -= shared
            retained |= shared
        files, directories = {}, set()
        for key in candidates:
            task = tasks[key]
            if task['status'] not in TERMINAL:
                raise WorkError('相关附件任务仍在处理中，请稍后再删除。')
            entries = list(task['context'].get('artifacts', []))
            if task['context'].get('artifact'):
                entries.append(task['context']['artifact'])
            for step in task['steps']:
                if step.get('action') == 'upload':
                    for relative, stamp in step.get('after', {}).items():
                        if stamp:
                            entries.append({'workspace_id': task['workspace_id'], 'path': relative, **stamp})
            for entry in entries:
                root = work.root(entry['workspace_id'])
                path = work.path(root, entry['path'])
                if not any(
                    path != managed and path.is_relative_to(managed) for managed in (work.upload_root, work.output_root)
                ):
                    continue
                # Protect aliases from retained tasks even when references use paths instead of IDs.
                if any(entry['path'] in set(strings(tasks[other])) for other in retained):
                    continue
                if path.exists():
                    no_link(path)
                    actual = work.fingerprint(path)
                    if actual.get('sha256') != entry.get('sha256'):
                        raise WorkError('相关文件已被修改，请先核对文件再删除对话。')
                    files.setdefault(str(path), {'original': str(path), 'staged': str(len(files)) + '.copy'})
                    if path.parent != root and path.parent.name == '任务-' + key:
                        directories.add(str(path.parent))
        root = store.path.parent / 'deletion-journal'
        root.mkdir(exist_ok=True)
        no_link(root)
        directory = root / uuid4().hex
        directory.mkdir()
        plan = {'conversation': conversation_id, 'files': list(files.values()), 'directories': sorted(directories)}
        temporary = directory / 'plan.tmp'
        with temporary.open('x', encoding='utf-8') as output:
            json.dump(plan, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, directory / 'plan.json')
        try:
            for item in plan['files']:
                move_exclusive(Path(item['original']), directory / item['staged'])
            deleted = store.delete_conversation(conversation_id, sorted(candidates))
        except Exception:
            finish(work, directory, plan)
            raise
        finish(work, directory, plan)
        return deleted
