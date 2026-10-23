"""Local attachment references and task outputs share the existing path and hash gates."""

import hashlib

from .filework import WorkError, no_link


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
    workspace = work.store.output_workspace()
    if not workspace or not workspace['enabled']:
        raise WorkError('请先选择并授权一个已有的成果文件夹。', 422)
    return workspace, work.root(workspace['id'])


def save_summary(work, task):
    result = next(item['result'] for item in task['steps'] if item['action'] == 'summarize')
    if task['context'].get('artifact'):
        artifact_bytes(work, task['id'])
        return True
    try:
        workspace, root = output_root(work)
    except WorkError:
        task['status'] = 'waiting_output'
        task['context']['pause'] = {'reason': '总结已完成，请选择成果文件夹后保存；继续时不会重新调用总结模型。'}
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
        item = work.task(task_id)['context'].get('artifact')
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
