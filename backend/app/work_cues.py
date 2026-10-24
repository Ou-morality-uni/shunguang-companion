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
        '好了，札记已经存好啦，点开成果就能看。',
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
    'waiting_limit': [
        '这份卷宗还有不少线索呢。我把读到的位置记好了，接下来要不要继续，你来定。',
        '这一轮先整理到这里，已经做好的都留着。剩下的范围写在下面，等你点头我再接着看。',
        '资料比一开始看起来还多些。我先留好进度，继续之前，咱们核对一下后面的安排。',
    ],
    'waiting_output': [
        '总结已经理好了，不过保存的地方暂时打不开。内容先留着，修好后就能接着存。',
        '札记还在，保存时遇到了一点麻烦。咱们看看目录的情况，不用重新整理。',
    ],
    'recognizing': ['这里有些图像线索，我来仔细辨一辨。', '接下来看看这些图表，细节也得照顾到。'],
    'summarizing': [
        '读到的线索准备好了，我来把它们串起来。',
        '接下来整理要点，也把对应的出处留好。',
        '嗯，我来把这些内容归拢成一份清楚的札记。',
    ],
    'saving': ['这份札记整理好了，我把它单独保存下来。', '内容已经备好，接下来把成果收妥。'],
}


class WorkCues:
    def __init__(self, store):
        self.store, self.lock = store, RLock()
        self.recent = deque(maxlen=5)
        self.started = {}
        self.generated = set()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='work-cue')
        self.closed = False

    def emit(self, task, kind, phrases=None):
        with self.lock:
            bank = phrases or PHRASES[kind]
            choices = [text for text in bank if text not in self.recent] or bank
            text = secrets.choice(choices)
            self.recent.append(text)
            self.store.add_work_event(task['id'], kind, text)
            if kind == 'start':
                self.started[task['id']] = time.monotonic()
            elif kind == 'progress':
                self.started.setdefault(task['id'], time.monotonic())
            elif kind in (
                'complete',
                'partial',
                'failed',
                'cancelled',
                'restored',
                'authorization',
                'waiting_limit',
                'waiting_output',
            ):
                self.started.pop(task['id'], None)
                self.generated.discard(task['id'])

    def stage(self, task, phase):
        context = task.setdefault('context', {})
        context['stage'] = phase
        announced = context.setdefault('announced_stages', [])
        if phase in announced:
            return
        announced.append(phase)
        self.store.save_file_task(task)
        if phase == 'reading':
            return  # The start/resume cue already announces reading.
        task_id = task['id']
        if (
            self.closed
            or task_id in self.generated
            or time.monotonic() - self.started.get(task_id, time.monotonic()) < 8
            or not feature_config.load().tts.work_prompts
            or not feature_config.load().tts.enabled
            or context.setdefault('budget', {}).get('calls', 0) >= 20
        ):
            self.emit(task, 'progress', PHRASES[phase])
            return
        value = config.load_config()
        if not config.public_config(value)['configured']:
            self.emit(task, 'progress', PHRASES[phase])
            return
        self.generated.add(task_id)
        context['budget']['calls'] = context['budget'].get('calls', 0) + 1
        self.store.save_file_task(task)
        value = value.model_copy(update={'llm_max_tokens': 128, 'llm_timeout': 8})

        def generate():
            try:
                latest = self.store.get_file_task(task_id)
                if (
                    self.closed
                    or not latest
                    or latest['status'] != 'running'
                    or latest['context'].get('stage') != phase
                ):
                    return
                messages = build_messages(
                    [],
                    capabilities='你正在处理文件任务，仍未完成。只说一句自然的工作中短提示，不超过40字。不虚构进度、完成状态或人物设定，不使用代码或百分比。',
                )
                messages.append(
                    HumanMessage(
                        content='当前真实阶段：'
                        + {
                            'recognizing': '开始理解资料中的图像',
                            'summarizing': '开始综合已读取的资料',
                            'saving': '开始保存已整理的总结',
                        }[phase]
                    )
                )

                def active():
                    from .filework import TaskCancelled

                    record = self.store.get_file_task(task_id)
                    if (
                        self.closed
                        or not record
                        or record['status'] != 'running'
                        or record['context'].get('stage') != phase
                    ):
                        raise TaskCancelled()

                text = asyncio.run(document_models.invoke(value, messages, active)).strip()
                if not 4 <= len(text) <= 50 or re.search(r'```|[%％]|已经完成|读完了|整理好|https?://', text):
                    raise ValueError('工作提示未满足表达约束')
                with self.lock:
                    latest = self.store.get_file_task(task_id)
                    if (
                        not self.closed
                        and latest
                        and latest['status'] == 'running'
                        and latest['context'].get('stage') == phase
                    ):
                        self.store.add_work_event(task_id, 'progress', text)
            except Exception:
                latest = self.store.get_file_task(task_id)
                if (
                    not self.closed
                    and latest
                    and latest['status'] == 'running'
                    and latest['context'].get('stage') == phase
                ):
                    self.emit(task, 'progress', PHRASES[phase])

        self.pool.submit(generate)

    def tick(self, task, check):
        check()  # Speech follows real stage changes; time alone never adds a progress cue.

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=True, cancel_futures=True)
