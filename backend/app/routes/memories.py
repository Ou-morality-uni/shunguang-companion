import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import runtime
from ..llm import build_model, friendly_error
from ..memory import summarize
from ..runtime import require_config, require_conversation
from ..schemas import HistorySourceOut, MemoryOut

router = APIRouter()


class UserProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nickname: str = Field(default='小师妹', min_length=1, max_length=40)
    city: str = Field(default='', max_length=80)
    age: int | None = Field(default=None, ge=1, le=120, strict=True)

    @field_validator('nickname', 'city')
    @classmethod
    def clean(cls, value, info):
        value = value.strip()
        if any(ord(char) < 32 for char in value) or (info.field_name == 'nickname' and not value):
            raise ValueError('资料内容不正确')
        return value


@router.get('/api/profile', response_model=UserProfile)
def profile():
    return runtime.store.user_profile()


@router.patch('/api/profile', response_model=UserProfile)
def update_profile(payload: UserProfile):
    return runtime.store.update_user_profile(payload.model_dump(exclude_unset=True))


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


class MemoryStatusOut(BaseModel):
    queued: int
    running: int
    failed: int
    paused: int
    summaries: int


@router.get('/api/memories/status', response_model=MemoryStatusOut)
def memory_status():
    return runtime.store.memory_status()


@router.get('/api/memories/history/{message_id}', response_model=HistorySourceOut)
def history_source(message_id: str):
    result = runtime.store.history_source(message_id)
    if result is None:
        raise HTTPException(404, '来源对话已删除、遗忘或不再可用。')
    return result


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
