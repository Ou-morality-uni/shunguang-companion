import asyncio
import json
import re
import time

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel, Field, field_validator

from .. import runtime, stickers
from ..constants import CHAT_TIMEOUT, HISTORY_WINDOW, MAX_MESSAGE_LENGTH, MAX_TOOL_CALLS, MAX_TOOL_ROUNDS
from ..llm import EmptyResponseError, build_messages, build_model, extract_text, friendly_error
from ..logging_setup import report_error
from ..runtime import require_config, require_conversation
from ..schemas import ConversationOut, MessageOut

router = APIRouter()


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


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)

    @field_validator('content')
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('消息不能为空')
        return value.strip()


@router.get('/api/conversations', response_model=list[ConversationOut])
def conversations():
    return runtime.store.list_conversations()


@router.post('/api/conversations', status_code=201, response_model=ConversationOut)
def create_conversation():
    return runtime.store.create_conversation()


@router.get('/api/conversations/{conversation_id}/messages', response_model=list[MessageOut])
def get_messages(
    conversation_id: str,
    limit: int | None = Query(default=None, ge=1, le=500),
    before: int | None = Query(default=None, ge=1),
):
    require_conversation(conversation_id)
    return runtime.store.messages(conversation_id, limit, before)


def event(name: str, data: dict) -> str:
    return f'event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


async def cancellable_chunks(model, history, stop):
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


@router.delete('/api/conversations/{conversation_id}', status_code=204)
async def delete_conversation(conversation_id: str):
    async with runtime.mutation_lock:
        if conversation_id in runtime.busy:
            raise HTTPException(409, '请先停止回复，再删除这段对话。')
        if not await asyncio.to_thread(runtime.store.delete_conversation, conversation_id):
            raise HTTPException(404, '对话不存在')
    return Response(status_code=204)


@router.post('/api/chat/{conversation_id}/stop')
async def stop_chat(conversation_id: str):
    await asyncio.to_thread(require_conversation, conversation_id)
    stop = runtime.stops.get(conversation_id)
    finished = runtime.finished.get(conversation_id)
    if stop:
        stop.set()
    if finished:
        try:
            committed = await asyncio.wait_for(asyncio.shield(finished), timeout=30)
            if not committed:
                raise HTTPException(503, '回复已停止，但记录保存失败，请检查数据目录。')
        except TimeoutError:
            raise HTTPException(504, '停止仍在处理中，请稍后刷新对话。')
    return {'ok': True}


@router.post('/api/chat')
async def chat(payload: ChatRequest):
    config = await asyncio.to_thread(require_config)
    model = await asyncio.to_thread(build_model, config)
    # Reserve before yielding to I/O. Deletion shares the gate; never discard a live lock.
    async with runtime.mutation_lock:
        if payload.conversation_id:
            await asyncio.to_thread(require_conversation, payload.conversation_id)
            if payload.conversation_id in runtime.busy:
                raise HTTPException(409, '这段对话正在回复中，请稍后再发。')
        user_message = await asyncio.to_thread(runtime.store.begin_turn, payload.conversation_id, payload.content)
        conversation_id = user_message['conversation_id']
        runtime.busy.add(conversation_id)
        stop = runtime.stops[conversation_id] = asyncio.Event()
        finished = runtime.finished[conversation_id] = asyncio.get_running_loop().create_future()

    async def io(function, *args):
        # Starlette shields thread work from disconnect cancellation, including final persistence.
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(function, *args)

    async def stream():
        text = ''
        persisted = False
        metadata = {'sources': [], 'context_sources': [], 'tools': []}
        assistant = None
        try:
            assistant = await io(runtime.store.add_message, conversation_id, 'assistant', '', 'streaming')
            stored_history = await io(runtime.store.messages, conversation_id, HISTORY_WINDOW + 1)
            yield event('user', user_message)
            from .. import memory, rag, retrieval_router, tools
            from ..feature_config import load_features

            features = await io(load_features)
            sticker_catalog = await io(stickers.load_catalog)
            schemas = tools.schemas(features) + memory.schemas(features.memory)
            decision = await io(retrieval_router.route, payload.content)
            metadata['retrieval'] = {'domain': decision['domain'], 'candidate_count': 0, 'context_count': 0}
            try:
                memory_result = await interruptible(
                    memory.update_from_message(runtime.store, model, user_message, features.memory, stored_history),
                    stop,
                )
            except StopRequested:
                raise
            except Exception:
                memory_result = {'status': 'failed'}
            recalled = (
                await io(runtime.store.recall_history, payload.content, conversation_id)
                if features.memory.recall_history and decision['domain'] in ('memory', 'memory_knowledge')
                else []
            )
            try:
                if decision['search'] and (await interruptible(asyncio.to_thread(rag.status), stop)).get('ready'):
                    permit = bool(re.search(r'(允许|接受|可以)剧透', payload.content)) and not bool(
                        re.search(r'(不允许|不接受|不要|禁止|不能).*剧透', payload.content)
                    )
                    sources = await interruptible(asyncio.to_thread(rag.search, decision['query'], 8, permit), stop)
                    metadata['retrieval']['candidate_count'] = len(sources)
                    sources = await io(retrieval_router.relevant_sources, decision['query'], sources)
                    metadata['context_sources'] = [
                        {**s, 'number': i + 1, 'usage': 'context'} for i, s in enumerate(sources)
                    ]
                    metadata['retrieval']['context_count'] = len(sources)
            except StopRequested:
                raise
            except Exception:
                yield event(
                    'tool',
                    {
                        'name': 'knowledge',
                        'status': 'error',
                        'message': '知识检索暂时不可用，本次不使用未返回的检索结果。',
                    },
                )
            capabilities = (
                '用户事实与实际记忆操作结果在参考数据中；不承诺没有成功写入的记忆。日常不要复述技术说明。工具可用列表：'
                + ','.join(t.get('name', t.get('function', {}).get('name', '')) for t in schemas)
                + '。工具关闭时不得假称查过天气或网页；需要实时信息请使用可用工具。一次回复最多4次工具调用。TTS和休息提醒由网页设置及播放控件管理，不能通过聊天声称改变设置或创建后台通知。'
                + stickers.instruction(sticker_catalog)
            )
            history = await io(
                build_messages,
                stored_history,
                memory.recall_facts(await io(runtime.store.list_memories), payload.content),
                metadata['context_sources'],
                capabilities,
                {'memory_action': memory_result, 'shared_history': recalled},
            )
            count, last_save = 0, time.monotonic()
            sticker_hint = ''
            async with asyncio.timeout(CHAT_TIMEOUT):
                for round_index in range(MAX_TOOL_ROUNDS):
                    decoration = stickers.ReplyDecoration()
                    round_text = ''
                    current = (
                        model.bind_tools(schemas)
                        if schemas
                        and hasattr(model, 'bind_tools')
                        and count < MAX_TOOL_CALLS
                        and round_index < MAX_TOOL_ROUNDS - 1
                        else model
                    )
                    accumulated = None
                    async for chunk in cancellable_chunks(current, history, stop):
                        accumulated = chunk if accumulated is None else accumulated + chunk
                        delta = decoration.push(extract_text(chunk.content))
                        if delta:
                            round_text += delta
                            text += delta
                            yield event('delta', {'text': delta})
                            if time.monotonic() - last_save >= 0.4:
                                await io(runtime.store.update_message, assistant['id'], text, 'streaming', metadata)
                                last_save = time.monotonic()
                    tail = decoration.finish()
                    if tail:
                        round_text += tail
                        text += tail
                        yield event('delta', {'text': tail})
                    if stop.is_set():
                        result = await io(
                            runtime.store.update_message,
                            assistant['id'],
                            text or '回复已停止。',
                            'interrupted',
                            metadata,
                        )
                        persisted = True
                        yield event('done', result)
                        return
                    calls = getattr(accumulated, 'tool_calls', []) if accumulated else []
                    if not calls:
                        sticker_hint = decoration.hint
                        break
                    history.append(AIMessage(content=round_text, tool_calls=calls))
                    allowed_names = {t.get('name', t.get('function', {}).get('name')) for t in schemas}
                    for call in calls:
                        if stop.is_set():
                            break
                        name, args = call['name'], call['args']
                        count += 1
                        state = {'id': call['id'], 'name': name, 'status': 'running'}
                        yield event('tool', state)
                        if count > MAX_TOOL_CALLS or name not in allowed_names:
                            result = {'ok': False, 'error': '工具未启用或调用次数已达上限。'}
                        elif name in ('remember_user_fact', 'recall_conversations'):
                            result = await io(
                                memory.execute, name, args, runtime.store, user_message, features.memory, stored_history
                            )
                        else:
                            try:
                                result = await interruptible(
                                    asyncio.wait_for(tools.execute(name, args), timeout=25), stop
                                )
                            except StopRequested:
                                raise
                            except Exception:
                                result = {'ok': False, 'error': '工具执行失败或超时，请稍后重试。'}
                        state = {
                            **state,
                            'status': 'complete' if result.get('ok', False) else 'error',
                            'result': result,
                        }
                        metadata['tools'].append(state)
                        yield event('tool', state)
                        history.append(
                            ToolMessage(content=json.dumps(result, ensure_ascii=False)[:16000], tool_call_id=call['id'])
                        )
            if not text.strip():
                raise EmptyResponseError()
            metadata['sources'] = retrieval_router.cited_sources(text, metadata['context_sources'])
            metadata['sticker'] = stickers.choose(sticker_catalog, sticker_hint, stored_history, assistant['id'])
            await io(runtime.store.update_summary, conversation_id)
            result = await io(runtime.store.update_message, assistant['id'], text, 'complete', metadata)
            persisted = True
            yield event('done', result)
        except StopRequested:
            result = await io(
                runtime.store.update_message, assistant['id'], text or '回复已停止。', 'interrupted', metadata
            )
            persisted = True
            yield event('done', result)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            report_error('chat', error)
            result = (
                await io(
                    runtime.store.update_message, assistant['id'], text or friendly_error(error), 'error', metadata
                )
                if assistant
                else await io(runtime.store.add_message, conversation_id, 'assistant', friendly_error(error), 'error')
            )
            persisted = True
            yield event('error', {'message': friendly_error(error), 'record': result})
        finally:
            try:
                if not persisted:
                    if assistant:
                        import anyio

                        with anyio.CancelScope(shield=True):
                            await io(
                                runtime.store.update_message,
                                assistant['id'],
                                text or '回复已停止。',
                                'interrupted',
                                metadata,
                            )
                            persisted = True
            finally:
                runtime.busy.discard(conversation_id)
                runtime.stops.pop(conversation_id, None)
                runtime.finished.pop(conversation_id, None)
                if not finished.done():
                    finished.set_result(persisted)

    return StreamingResponse(
        stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )
