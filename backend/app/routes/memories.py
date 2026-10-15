import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import runtime
from ..llm import build_model, friendly_error
from ..memory import summarize
from ..runtime import require_config, require_conversation
from ..schemas import MemoryOut

router = APIRouter()


class MemorySummaryRequest(BaseModel):
    conversation_id: str


class CandidateConfirm(BaseModel):
    id: str
    key: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=600)


class MemoryConfirmRequest(BaseModel):
    candidates: list[CandidateConfirm] = Field(min_length=1, max_length=30)


class MemoryEditRequest(BaseModel):
    value: str = Field(min_length=1, max_length=600)


@router.get('/api/memories', response_model=list[MemoryOut])
def memories():
    return runtime.store.list_memories()


@router.post('/api/memories/summarize')
async def summarize_memory(payload: MemorySummaryRequest):
    await asyncio.to_thread(require_conversation, payload.conversation_id)
    try:
        config = await asyncio.to_thread(require_config)
        model = await asyncio.to_thread(build_model, config)
        history = await asyncio.to_thread(runtime.store.messages, payload.conversation_id)
        candidates = await summarize(model, history)
        return {
            'candidates': await asyncio.to_thread(runtime.store.add_candidates, payload.conversation_id, candidates)
        }
    except HTTPException:
        raise
    except (ValueError, KeyError):
        raise HTTPException(502, '模型未返回可核对的记忆候选，请重试。没有保存任何事实。')
    except Exception as error:
        raise HTTPException(502, friendly_error(error))


@router.post('/api/memories/confirm')
def confirm_memory(payload: MemoryConfirmRequest):
    if any(not c.key.strip() or not c.value.strip() for c in payload.candidates):
        raise HTTPException(422, '记忆字段不能为空。')
    try:
        return runtime.store.confirm_candidates([c.model_dump() for c in payload.candidates])
    except ValueError as error:
        raise HTTPException(409, str(error))


@router.patch('/api/memories/{memory_id}')
def edit_memory(memory_id: str, payload: MemoryEditRequest):
    if not payload.value.strip():
        raise HTTPException(422, '记忆内容不能为空。')
    try:
        return runtime.store.edit_memory(memory_id, payload.value.strip())
    except ValueError:
        raise HTTPException(404, '记忆不存在。')


@router.delete('/api/memories/{memory_id}')
def delete_memory(memory_id: str):
    if not runtime.store.delete_memory(memory_id):
        raise HTTPException(404, '记忆不存在。')
    return {'ok': True}
