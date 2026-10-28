"""Local attachment references and task outputs share the existing path and hash gates."""

import hashlib
import os
import subprocess
from pathlib import Path
from sys import platform as sys_platform

from .filework import WorkError, no_link


def reveal(work, identity, version):
    from .office_resources import resource_bytes

    with work.gate:
        item, _ = resource_bytes(work, 'artifact', identity, version)
        path = work.path(work.root(item['workspace_id']), item['path'])
        if sys_platform != 'win32':
            raise WorkError('此环境暂不支持打开本机文件管理器，请使用下载按钮。', 422)
        explorer = str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'explorer.exe')
        subprocess.Popen([explorer, '/select,', str(path)], shell=False)
    return {'ok': True}


def attachment(work, task_id):
    task = work.task(task_id)
    if task['status'] != 'complete' or len(task['steps']) != 1 or task['steps'][0]['action'] != 'upload':
        raise WorkError('附件不存在或尚未保存。', 404)
    step = task['steps'][0]
    root = work.root(task['workspace_id'])
    if root != work.upload_root:
        raise WorkError('此记录不是上传附件。', 403)
    work.check_state(root, step['after'])
    return {
        'id': task_id,
        'workspace_id': task['workspace_id'],
        'path': step['path'],
        'name': step.get('result', {}).get('name', step['path']),
        'bytes': step['after'][step['path']]['bytes'],
        'version': step['after'][step['path']]['sha256'],
    }


def attachment_bytes(work, task_id):
    with work.gate:
        item = attachment(work, task_id)
        root = work.root(item['workspace_id'])
        path = work.path(root, item['path'])
        data = path.read_bytes()
        work.check_state(root, work.task(task_id)['steps'][0]['after'])
        return item, data


def output_root(work):
    workspace = work.default_output_workspace()
    return workspace, work.root(workspace['id'])


def save_file(work, task, name, data, validation):
    from .filework import MAX_FILE_BYTES

    if len(data) > MAX_FILE_BYTES:
        raise WorkError('成果超过单文件 20 MiB 上限，请缩小任务范围。', 422)
    with work.gate:
        workspace, root = output_root(work)
        relative_directory = f'任务-{task["id"]}'
        directory = work.path(root, relative_directory)
        owner = {'workspace_id': workspace['id'], 'path': relative_directory}
        if directory.exists():
            if task['context'].get('output_directory') != owner:
                raise WorkError('本次成果目录已被其他程序创建，请检查后重试。')
        else:
            directory.mkdir()
            task['context']['output_directory'] = owner
            work.store.save_file_task(task)
        no_link(directory)
        path = work.path(root, relative_directory + '/' + name)
        item = {
            'id': str(len(task['context'].get('artifacts', []))),
            'workspace_id': workspace['id'],
            'path': relative_directory + '/' + name,
            'name': name,
            'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data),
            'validation': validation,
        }
        work.put(path, data, None, mode=0o600)
        task['context'].setdefault('artifacts', []).append(item)
        task['context'].setdefault('artifact', item)
        work.store.save_file_task(task)
        return item


def save_summary(work, task):
    result = next(item['result'] for item in task['steps'] if item['action'] == 'summarize')
    if task['context'].get('artifact'):
        artifact_bytes(work, task['id'])
        return True
    try:
        workspace, root = output_root(work)
    except (WorkError, OSError):
        task['status'] = 'waiting_output'
        task['context']['pause'] = {
            'reason': '总结已完成，但项目成果目录暂不可写；请检查目录权限后重试保存，无需重新总结。'
        }
        return False
    coverage = []
    for step in task['steps']:
        if step['action'] != 'read_document':
            continue
        value = step.get('result', {})
        coverage.append(
            f'- {step["path"]}：{value.get("coverage", "按任务指定范围读取")}；'
            + ('存在未读或未识别部分' if value.get('partial') else '本次范围已处理')
        )
    warnings = list(dict.fromkeys(result.get('warnings', [])))
    text = '# 资料总结\n\n' + result['summary'] + '\n\n## 阅读范围与来源\n\n' + '\n'.join(coverage)
    if warnings:
        text += '\n\n## 处理说明\n\n' + '\n'.join('- ' + item for item in warnings)
    data = (text + '\n').encode('utf-8')
    relative = f'任务-{task["id"]}/资料总结.md'
    work.cues.stage(task, 'saving')
    with work.gate:
        root = work.root(workspace['id'])
        directory = work.path(root, f'任务-{task["id"]}')
        if directory.exists():
            if task['context'].get('output_directory') != {'workspace_id': workspace['id'], 'path': directory.name}:
                raise WorkError('本次成果目录已被其他程序创建，请检查后重试。')
        else:
            directory.mkdir()
            task['context']['output_directory'] = {'workspace_id': workspace['id'], 'path': directory.name}
            work.store.save_file_task(task)
        no_link(directory)
        path = work.path(root, relative)
        stamp = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        artifact = {'workspace_id': workspace['id'], 'path': relative, 'name': '资料总结.md', **stamp}
        task['context']['artifact'] = artifact
        work.store.save_file_task(task)
        work.put(path, data, None, mode=0o600)
    return True


def artifact_bytes(work, task_id):
    with work.gate:
        index = 0
        if '~' in task_id:
            task_id, raw_index = task_id.rsplit('~', 1)
            if not raw_index.isdigit() or len(raw_index) > 3:
                raise WorkError('成果不存在。', 404)
            index = int(raw_index)
        context = work.task(task_id)['context']
        artifacts = context.get('artifacts') or ([context['artifact']] if context.get('artifact') else [])
        item = artifacts[index] if index < len(artifacts) else None
        if not item:
            raise WorkError('本任务还没有已保存的总结文件。', 404)
        root = work.root(item['workspace_id'])
        path = work.path(root, item['path'])
        actual = work.fingerprint(path)
        if actual is None or any(actual[key] != item[key] for key in ('sha256', 'bytes')):
            raise WorkError('成果文件已被外部修改或移动，请在保存位置查看当前文件。')
        data = path.read_bytes()
        work.check_state(root, {item['path']: actual})
        return item, data


def task_context(work, conversation_id):
    """Only this conversation's task facts; reference text remains untrusted data."""
    records = []
    remaining = 16000
    for task in work.store.list_file_tasks(8, conversation_id):
        summaries = [
            step.get('result', {}).get('summary', '') for step in task['steps'] if step['action'] == 'summarize'
        ]
        summary = '\n'.join(summaries)
        clipped = summary[:remaining]
        remaining -= len(clipped)
        records.append(
            {
                'id': task['id'],
                'title': task['title'],
                'status': task['status'],
                'error': task['error'],
                'summary': clipped,
                'summary_preview_only': len(clipped) < len(summary),
            }
        )
    return records[::-1]
