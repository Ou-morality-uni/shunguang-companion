import asyncio
import json
import random

from .logging_setup import metric, request_id


class StopRequested(Exception):
    pass


async def interruptible(awaitable, stop):
    work = asyncio.ensure_future(awaitable)
    stopper = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({work, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if stopper in done:
            raise StopRequested()
        return work.result()
    finally:
        for task in (work, stopper):
            if not task.done():
                task.cancel()
        await asyncio.gather(work, stopper, return_exceptions=True)


def event(name: str, data: dict) -> str:
    return f'event: {name}\ndata: {json.dumps({**data, "request_id": data.get("request_id") or request_id.get()}, ensure_ascii=False)}\n\n'


def tool_content(result):
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= 16000:
        return text
    return json.dumps(
        {
            'ok': result.get('ok', False),
            'truncated': True,
            'task_id': (result.get('task') or {}).get('id'),
            'message': '工具结果过长，以下只是部分预览。不能将未返回的内容当作已读资料；文件任务完整结果可在工作台查看。',
            'preview': text[:12000],
        },
        ensure_ascii=False,
    )


async def cancellable_chunks(model, history, stop):
    import httpx
    from openai import APIConnectionError

    for attempt in range(2):
        received = False
        try:
            async for chunk in _single_attempt_chunks(model, history, stop):
                received = True
                yield chunk
            return
        except Exception as error:
            status = getattr(error, 'status_code', None)
            transient = isinstance(error, (httpx.TransportError, APIConnectionError)) or status in (
                429,
                500,
                502,
                503,
                504,
                529,
            )
            if received or attempt or not transient or stop.is_set():
                raise
            metric('model_retry', 0, attempt=attempt + 1)
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.2 + random.random() * 0.2)
                return
            except TimeoutError:
                pass


async def _single_attempt_chunks(model, history, stop):
    iterator = model.astream(history).__aiter__()
    pending = None
    stopper = asyncio.create_task(stop.wait())
    try:
        while not stop.is_set():
            pending = asyncio.create_task(anext(iterator))
            done, _ = await asyncio.wait({pending, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if stopper in done:
                return
            try:
                yield pending.result()
            except StopAsyncIteration:
                return
    finally:
        if pending and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        stopper.cancel()
        await asyncio.gather(stopper, return_exceptions=True)
        if hasattr(iterator, 'aclose'):
            await iterator.aclose()
