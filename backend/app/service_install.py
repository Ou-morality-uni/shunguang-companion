"""Local, fixed-scope retrieval installation for the Windows foreground app."""

import os
import subprocess
import sys
from threading import Lock, Thread

from . import config, rag
from .config import CONFIG_LOCK
from .rag import read_json, write_json

gate = Lock()
state = {'state': 'idle', 'stage': None, 'error': None}
stages = {'dependencies': '安装检索依赖', 'model_download': '下载并校验模型', 'indexing': '构建并验证索引'}
failures = {
    'preflight': '检索安装环境或磁盘空间不足',
    'retrieval_dependencies': '检索依赖安装失败；若是系统运行库问题，请先停止后端并修复基础环境',
    'model_download': '模型下载或完整性校验失败',
    'model_inference_and_index': '模型运行、索引构建或检索验收失败',
}


def snapshot():
    with gate:
        return dict(state)


def run():
    stage = '准备知识库'
    reason = None
    try:
        if not rag.status()['ready']:
            with subprocess.Popen(
                [sys.executable, '-u', str(config.ROOT / 'scripts/install-project.py'), '--rag-only', '--online-rag'],
                cwd=config.ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW,
            ) as child:
                for line in child.stdout:
                    value = line.strip().removeprefix('RAG_STAGE: ')
                    if line.startswith('RAG_STAGE: ') and value in stages:
                        stage = stages[value]
                        with gate:
                            state.update(stage=stage)
                    if line.startswith('RAG_FAILED: '):
                        reason = failures.get(line.strip().removeprefix('RAG_FAILED: '))
                if child.wait() != 0:
                    raise RuntimeError('installation failed')
        if not rag.status()['ready']:
            raise RuntimeError('retrieval verification failed')
        with CONFIG_LOCK:
            path = config.DATA_DIR / 'install/preferences.json'
            preferences = read_json(path, {})
            preferences.setdefault('mode', 'lite')
            preferences.setdefault('qq', False)
            preferences['knowledge_enabled'] = True
            write_json(path, preferences)
    except Exception as error:
        from .logging_setup import report_error

        report_error('rag_service_install', error)
        with gate:
            state.update(state='failed', error=(reason or f'{stage}失败') + '。检查环境后可重试。')
    else:
        with gate:
            state.update(state='ready', stage=None, error=None)


def start():
    with gate:
        if state['state'] == 'running':
            return dict(state)
        state.update(state='running', stage='准备知识库', error=None)
        Thread(target=run, name='rag-service-install', daemon=True).start()
        return dict(state)


def supported():
    return (
        sys.platform == 'win32'
        and os.environ.get('SHUNGUANG_INTERACTIVE_DESKTOP') == '1'
        and not config.server_mode()
        and config.DATA_DIR.resolve() == (config.ROOT / 'data').resolve()
    )
