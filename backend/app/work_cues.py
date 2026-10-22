"""Task facts choose short character cues; optional long-task wording is non-blocking."""

import asyncio
import re
import secrets
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import RLock

from langchain_core.messages import HumanMessage

from . import config, document_models, feature_config
from .llm import build_messages

PHRASES = {
    'start': [
        '交给我吧，我先把这些内容理一理。',
        '那就从这份卷宗开始吧，有要紧的地方我会记下来。',
        '我先看看手边这些资料，稍等我一下呀。',
        '让我理理线索，咱们一步一步来。',
    ],
    'progress': [
        '我再把手边的线索理顺一些，有缺漏的地方也会说明。',
        '我还在看呢，有些细节值得仔细理一理。',
        '嗯，先把这几处内容核对清楚。',
    ],
    'authorization': [
        '这部分是图片，我现在还看不明白。师父教过我一个办法，要我借它来看看吗？',
        '这里还有些图像需要借个小窍门，先看看下面的说明，再决定要不要交给我吧。',
        '这页卷宗还得换个办法才能看清，具体会用什么，我写在下面啦。',
    ],
    'complete': [
        '整理好啦，结果就在这里，我们一起看看吧。',
        '手边这件事办好啦，有要紧的内容我都留在结果里了。',
        '嗯，这一份处理完了，来看看吧。',
        '好了，我把这次的结果整理在下面啦。',
    ],
    'partial': [
        '这次能处理的部分已经整理好啦，没看清的地方也标出来了。',
        '先把已经读到的内容交给你，暂时没能处理的部分，我也注明了。',
    ],
    'failed': [
        '这里遇到了点麻烦，我把原因写下来了，已经完成的部分也保留着。',
        '这一步暂时没能走通，我先停下来，咱们看看具体原因。',
    ],
    'cancelled': ['好，先停在这里，已做过的事情可以在记录里查看。', '收到，我先收手，已经完成的部分会留好。'],
    'restored': ['这次修改已经恢复好啦，你再看看。', '好啦，能恢复的内容已经按记录还原了。'],
}


class WorkCues:
    def __init__(self, store):
        self.store, self.lock = store, RLock()
        self.recent = deque(maxlen=5)
        self.started = {}
        self.generated = set()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='work-cue')
        self.closed = False

    def emit(self, task, kind):
        with self.lock:
            choices = [text for text in PHRASES[kind] if text not in self.recent] or PHRASES[kind]
            text = secrets.choice(choices)
            self.recent.append(text)
            self.store.add_work_event(task['id'], kind, text)
            if kind == 'start':
                self.started[task['id']] = time.monotonic()
            elif kind == 'progress':
                self.started.setdefault(task['id'], time.monotonic())
            elif kind in ('complete', 'partial', 'failed', 'cancelled', 'restored', 'authorization'):
                self.started.pop(task['id'], None)
                self.generated.discard(task['id'])

    def tick(self, task, check):
        task_id = task['id']
        if (
            self.closed
            or task_id in self.generated
            or time.monotonic() - self.started.get(task_id, time.monotonic()) < 8
        ):
            return
        self.generated.add(task_id)
        if not feature_config.load().tts.work_prompts or not feature_config.load().tts.enabled:
            return
        value = config.load_config()
        if not config.public_config(value)['configured']:
            return
        value = value.model_copy(update={'llm_max_tokens': 128, 'llm_timeout': 8})

        def generate():
            try:
                latest = self.store.get_file_task(task_id)
                if self.closed or not latest or latest['status'] != 'running':
                    return
                messages = build_messages(
                    [],
                    capabilities='你正在处理文件任务，仍未完成。只说一句自然的工作中短提示，不超过40字。不虚构进度、完成状态或人物设定，不使用代码或百分比。',
                )
                messages.append(HumanMessage(content='当前真实状态：资料仍在读取、识别或整理中。可以换个自然的说法。'))
                text = asyncio.run(document_models.invoke(value, messages, check)).strip()
                if not 4 <= len(text) <= 50 or re.search(r'```|[%％]|已经完成|读完了|整理好|https?://', text):
                    return
                with self.lock:
                    latest = self.store.get_file_task(task_id)
                    if not self.closed and latest and latest['status'] == 'running':
                        self.store.add_work_event(task_id, 'progress', text)
            except Exception:
                pass  # Optional wording must never fail the file task or trigger a paid retry.

        self.pool.submit(generate)

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=True, cancel_futures=True)
