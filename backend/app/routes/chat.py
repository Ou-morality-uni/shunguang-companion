import asyncio

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .. import runtime
from ..chat_models import ChatRequest
from ..llm import build_model
from ..model_choices import ModelChoice, ModelChoiceOut, default_choice, public_choice
from ..runtime import require_conversation
from ..schemas import ConversationOut, MessageOut
from ..turn_stream import cancellable_chunks, event, tool_content

__all__ = ['ChatRequest', 'cancellable_chunks', 'event', 'tool_content', 'generate_chat']
router = APIRouter()


@router.get('/api/conversations', response_model=list[ConversationOut])
def conversations():
    edition_ids = runtime.edition_conversations()
    return [item for item in runtime.store.list_conversations() if item['id'] not in edition_ids]


@router.post('/api/conversations', status_code=201, response_model=ConversationOut)
def create_conversation():
    return runtime.store.create_conversation()


@router.get('/api/conversations/{conversation_id}/messages', response_model=list[MessageOut])
def get_messages(
    conversation_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    before: int | None = Query(default=None, ge=1),
    after: int | None = Query(default=None, ge=1),
):
    require_conversation(conversation_id)
    if before is not None and after is not None:
        raise HTTPException(422, 'before 与 after 不能同时使用。')
    return runtime.store.messages(conversation_id, limit, before, after)


@router.get('/api/conversations/{conversation_id}/model', response_model=ModelChoiceOut)
def conversation_model(conversation_id: str):
    require_conversation(conversation_id)
    choice = runtime.store.conversation_model(conversation_id) or default_choice()
    return public_choice(choice)


@router.patch('/api/conversations/{conversation_id}/model', response_model=ModelChoiceOut)
async def update_conversation_model(conversation_id: str, payload: ModelChoice):
    runtime.require_web_conversation(conversation_id)
    async with runtime.mutation_lock:
        require_conversation(conversation_id)
        result = public_choice(payload.model_dump())
        runtime.store.set_conversation_model(conversation_id, payload.model_dump())
        return result


@router.delete('/api/conversations/{conversation_id}', status_code=204)
async def delete_conversation(conversation_id: str):
    runtime.require_web_conversation(conversation_id)
    async with runtime.mutation_lock:
        if conversation_id in runtime.busy:
            raise HTTPException(409, '请先停止回复，再删除这段对话。')
        from ..conversation_cleanup import delete
        from ..filework import WorkError

        try:
            deleted = (
                await asyncio.to_thread(delete, runtime.work, conversation_id)
                if runtime.work
                else await asyncio.to_thread(runtime.store.delete_conversation, conversation_id)
            )
        except WorkError as error:
            raise HTTPException(error.status, error.message) from None
        if not deleted:
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
async def chat(payload: ChatRequest, request: Request = None):
    return await generate_chat(payload, request)


async def generate_chat(payload: ChatRequest, request=None, **channel_options):
    from ..turn import generate_chat as run

    return await run(payload, request, model_factory=build_model, **channel_options)
