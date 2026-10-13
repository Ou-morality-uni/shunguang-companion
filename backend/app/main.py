import asyncio
import json
import time
import re
from pathlib import Path
from typing import Literal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

from .config import CONFIG_LOCK, DATA_DIR, ROOT, ModelConfig, load_config, public_config, save_config
from .config import saved_profiles, profile_config, find_saved_config
from .llm import build_messages, build_model, extract_text, friendly_error
from .store import Store
from . import access
from .providers import PRESETS, discover
from .memory import summarize
from langchain_core.messages import AIMessage, ToolMessage

store = Store(DATA_DIR / 'companion.sqlite3')
busy: set[str] = set()
stops: dict[str, asyncio.Event] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.initialize()
    yield


app = FastAPI(title='瞬光伴行 API', version='0.2.0', lifespan=lifespan)
app.middleware('http')(access.guard)


class SettingsUpdate(BaseModel):
    base_url: str = Field(max_length=500)
    model: str = Field(max_length=150)
    temperature: float = Field(ge=0, le=2)
    timeout: float = Field(ge=5, le=120)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    provider: str = Field(default='custom', max_length=40)
    protocol: Literal['openai', 'anthropic'] = 'openai'


class DiscoveryRequest(BaseModel):
    base_url: str = Field(max_length=500)
    provider: str = Field(default='custom', max_length=40)
    protocol: Literal['openai', 'anthropic'] = 'openai'
    api_key: SecretStr | None = None
    timeout: float = Field(default=20, ge=5, le=120)


class LoginRequest(BaseModel):
    password: SecretStr = Field(max_length=300)


@app.get('/api/auth/status')
def auth_status(request: Request):
    return {'required': access.lan_mode(), 'authenticated': access.authenticated(request)}


@app.post('/api/auth/login')
def auth_login(payload: LoginRequest, request: Request):
    return access.login(request, payload.password.get_secret_value())


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Framework validation errors can echo invalid input, including credentials.
    return JSONResponse(status_code=422, content={'detail': '输入格式不正确，请检查字段类型、长度和数值范围。'})


class ChatRequest(BaseModel):
    conversation_id: str
    content: str = Field(min_length=1, max_length=6000)

    @field_validator('content')
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('消息不能为空')
        return value.strip()


def require_conversation(conversation_id: str):
    if not store.get_conversation(conversation_id):
        raise HTTPException(404, '对话不存在')


def require_config():
    config = load_config()
    if not public_config(config)['configured']:
        raise HTTPException(503, '请在设置界面填写模型名称和 API 密钥，并保存配置。')
    return config


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '0.2.0', 'stage': 'Web 功能集成', 'storage': 'sqlite', 'model': public_config(load_config())}


@app.get('/api/settings')
def settings():
    return public_config(load_config())


@app.patch('/api/settings')
def update_settings(payload: SettingsUpdate):
    with CONFIG_LOCK:
        current = load_config()
        if payload.model.strip().lower().startswith('sk-'):
            raise HTTPException(422, '模型名称看起来是 API 密钥，请将密钥填写到 API 密钥栏。')
        submitted = payload.api_key.get_secret_value().strip() if payload.api_key else ''
        if len(submitted) > 2048 or any(char.isspace() for char in submitted):
            raise HTTPException(422, '密钥长度或格式不正确，请重新填写。')
        if payload.clear_api_key and submitted:
            raise HTTPException(422, '移除密钥与填写新密钥不能同时进行。')
        saved = find_saved_config(payload.base_url.rstrip('/'), payload.protocol)
        secret = '' if payload.clear_api_key else submitted or (saved.llm_api_key.get_secret_value() if saved else '')
        try:
            config = ModelConfig(**{**current.model_dump(), 'llm_base_url': payload.base_url, 'llm_model': payload.model.strip(), 'llm_temperature': payload.temperature, 'llm_timeout': payload.timeout, 'llm_api_key': SecretStr(secret), 'llm_provider': payload.provider, 'llm_protocol': payload.protocol})
        except ValidationError:
            raise HTTPException(422, 'API 地址格式不正确，请输入 HTTP(S) 地址。')
        try:
            save_config(config)
        except (OSError, RuntimeError):
            raise HTTPException(503, '配置未保存，请检查本机凭据存储后重试。')
        return public_config(config)


@app.get('/api/providers/presets')
def provider_presets():
    return PRESETS


@app.get('/api/providers/profiles')
def provider_profiles():
    return [{**public_config(profile_config(item)), 'id': item['id']} for item in saved_profiles() if item.get('llm_model')]


class ProfileActivate(BaseModel):
    id: str = Field(max_length=30)


@app.post('/api/providers/activate')
def provider_activate(payload: ProfileActivate):
    with CONFIG_LOCK:
        for item in saved_profiles():
            if item['id'] == payload.id:
                config = profile_config(item)
                save_config(config)
                return public_config(config)
    raise HTTPException(404, '保存的连接不存在。')


@app.post('/api/providers/discover')
async def provider_discover(payload: DiscoveryRequest):
    current = load_config()
    submitted = payload.api_key.get_secret_value().strip() if payload.api_key else ''
    if len(submitted)>2048 or any(c.isspace() for c in submitted):
        raise HTTPException(422, '密钥格式不正确。')
    saved = find_saved_config(payload.base_url.rstrip('/'), payload.protocol)
    if not submitted and not saved:
        raise HTTPException(422, '新接口需要填写对应密钥；已有密钥只用于已保存连接。')
    try:
        config = ModelConfig(llm_base_url=payload.base_url, llm_protocol=payload.protocol, llm_provider=payload.provider, llm_api_key=submitted or saved.llm_api_key, llm_timeout=payload.timeout)
        if not config.llm_api_key.get_secret_value():
            raise HTTPException(503, '请在 API 密钥栏填写密钥。')
        return await discover(config)
    except ValidationError:
        raise HTTPException(422, 'API 地址格式不正确。')
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502, friendly_error(error) + ' 模型发现失败，仍可手动填写实际模型 ID。')


@app.post('/api/providers/test')
async def test_provider():
    config = require_config()
    try:
        result = await build_model(config).ainvoke('请仅回复“连接成功”。')
        return {'ok': True, 'message': extract_text(result.content)[:150]}
    except Exception as error:
        raise HTTPException(502, friendly_error(error))


@app.get('/api/conversations')
def conversations():
    return store.list_conversations()


@app.post('/api/conversations', status_code=201)
def create_conversation():
    return store.create_conversation()


@app.get('/api/conversations/{conversation_id}/messages')
def get_messages(conversation_id: str):
    require_conversation(conversation_id)
    return store.messages(conversation_id)


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


@app.post('/api/chat/{conversation_id}/stop')
async def stop_chat(conversation_id: str):
    require_conversation(conversation_id)
    if conversation_id in stops:
        stops[conversation_id].set()
    return {'ok': True}


@app.post('/api/chat')
async def chat(payload: ChatRequest):
    require_conversation(payload.conversation_id)
    config = require_config()
    if payload.conversation_id in busy:
        raise HTTPException(409, '这段对话正在回复中，请稍后再发。')
    # Build before storing the turn so invalid model configuration cannot leave a stuck turn.
    model = build_model(config)
    busy.add(payload.conversation_id)
    stop = stops[payload.conversation_id] = asyncio.Event()
    try:
        user_message = store.add_message(payload.conversation_id, 'user', payload.content)
        stored_history = store.messages(payload.conversation_id)
    except Exception:
        busy.discard(payload.conversation_id)
        raise

    async def stream():
        text = ''
        persisted = False
        metadata = {'sources': [], 'tools': []}
        assistant = None
        try:
            assistant = store.add_message(payload.conversation_id, 'assistant', '', 'streaming')
            yield event('user', user_message)
            from . import tools, rag
            from .feature_config import load_features
            features = load_features()
            schemas = tools.schemas(features)
            try:
                if rag.status().get('ready'):
                    permit = bool(re.search(r'(允许|接受|可以)剧透', payload.content)) and not bool(re.search(r'(不允许|不接受|不要|禁止|不能).*剧透', payload.content))
                    sources = await asyncio.to_thread(rag.search, payload.content, 4, permit)
                    metadata['sources'] = [{**s, 'number': i+1} for i,s in enumerate(sources)]
                    if sources:
                        yield event('sources', {'sources': metadata['sources']})
            except Exception:
                yield event('tool', {'name': 'knowledge', 'status': 'error', 'message': '知识检索暂时不可用，本次不使用未返回的检索结果。'})
            capabilities = ('当前已确认长期事实仅来自参考数据。工具可用列表：' + ','.join(t.get('name', t.get('function', {}).get('name', '')) for t in schemas) + '。工具关闭时不得假称查过天气或网页；需要实时信息请使用可用工具。一次回复最多4次工具调用。TTS和休息提醒由网页设置及播放控件管理，不能通过聊天声称改变设置或创建后台通知。')
            history = build_messages(stored_history, store.list_memories(), metadata['sources'], capabilities)
            count, last_save = 0, time.monotonic()
            async with asyncio.timeout(180):
                for round_index in range(3):
                    current = model.bind_tools(schemas) if schemas and count < 4 and round_index < 2 else model
                    accumulated = None
                    async for chunk in cancellable_chunks(current, history, stop):
                        accumulated = chunk if accumulated is None else accumulated + chunk
                        delta = extract_text(chunk.content)
                        if delta:
                            text += delta
                            yield event('delta', {'text': delta})
                            if time.monotonic()-last_save >= .4:
                                store.update_message(assistant['id'], text, 'streaming', metadata)
                                last_save = time.monotonic()
                    if stop.is_set():
                        result = store.update_message(assistant['id'], text or '回复已停止。', 'interrupted', metadata)
                        persisted = True
                        yield event('done', result)
                        return
                    calls = getattr(accumulated, 'tool_calls', []) if accumulated else []
                    if not calls:
                        break
                    history.append(AIMessage(content=extract_text(accumulated.content), tool_calls=calls))
                    allowed_names = {t.get('name',t.get('function',{}).get('name')) for t in schemas}
                    for call in calls:
                        name, args = call['name'], call['args']
                        count += 1
                        state = {'id': call['id'], 'name': name, 'status': 'running'}
                        yield event('tool', state)
                        if count > 4 or name not in allowed_names:
                            result = {'ok': False, 'error': '工具未启用或调用次数已达上限。'}
                        else:
                            try:
                                result = await asyncio.wait_for(tools.execute(name, args), timeout=25)
                            except Exception:
                                result = {'ok': False, 'error': '工具执行失败或超时，请稍后重试。'}
                        state = {**state, 'status': 'complete' if result.get('ok', False) else 'error', 'result': result}
                        metadata['tools'].append(state)
                        yield event('tool', state)
                        history.append(ToolMessage(content=json.dumps(result, ensure_ascii=False)[:16000], tool_call_id=call['id']))
            if not text.strip():
                raise RuntimeError('Empty model response')
            result = store.update_message(assistant['id'], text, 'complete', metadata)
            persisted = True
            yield event('done', result)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            result = store.update_message(assistant['id'], text or friendly_error(error), 'error', metadata) if assistant else store.add_message(payload.conversation_id, 'assistant', friendly_error(error), 'error')
            persisted = True
            yield event('error', {'message': friendly_error(error), 'record': result})
        finally:
            try:
                if not persisted:
                    if assistant:
                        store.update_message(assistant['id'], text or '回复已停止。', 'interrupted', metadata)
            finally:
                busy.discard(payload.conversation_id)
                stops.pop(payload.conversation_id, None)

    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


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


@app.get('/api/memories')
def memories():
    return store.list_memories()


@app.post('/api/memories/summarize')
async def summarize_memory(payload: MemorySummaryRequest):
    require_conversation(payload.conversation_id)
    try:
        candidates = await summarize(build_model(require_config()), store.messages(payload.conversation_id))
        return {'candidates': store.add_candidates(payload.conversation_id, candidates)}
    except HTTPException:
        raise
    except (ValueError, KeyError):
        raise HTTPException(502, '模型未返回可核对的记忆候选，请重试。没有保存任何事实。')
    except Exception as error:
        raise HTTPException(502, friendly_error(error))


@app.post('/api/memories/confirm')
def confirm_memory(payload: MemoryConfirmRequest):
    if any(not c.key.strip() or not c.value.strip() for c in payload.candidates):
        raise HTTPException(422, '记忆字段不能为空。')
    try:
        return store.confirm_candidates([c.model_dump() for c in payload.candidates])
    except ValueError as error:
        raise HTTPException(409, str(error))


@app.patch('/api/memories/{memory_id}')
def edit_memory(memory_id: str, payload: MemoryEditRequest):
    if not payload.value.strip():
        raise HTTPException(422, '记忆内容不能为空。')
    try:
        return store.edit_memory(memory_id, payload.value.strip())
    except ValueError:
        raise HTTPException(404, '记忆不存在。')


@app.delete('/api/memories/{memory_id}')
def delete_memory(memory_id: str):
    if not store.delete_memory(memory_id):
        raise HTTPException(404, '记忆不存在。')
    return {'ok': True}


class RagQuery(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=4, ge=1, le=10)
    allow_spoilers: bool = False


@app.get('/api/rag/status')
def rag_status():
    from . import rag
    return rag.status()


@app.post('/api/rag/rebuild')
async def rag_rebuild():
    from . import rag
    try:
        return await asyncio.to_thread(rag.rebuild)
    except Exception:
        raise HTTPException(503, '索引构建失败，请查看本机检索安装与模型文件状态。')


@app.post('/api/rag/search')
async def rag_search(payload: RagQuery):
    from . import rag
    try:
        return {'sources': await asyncio.to_thread(rag.search, payload.query, payload.limit, payload.allow_spoilers)}
    except Exception:
        raise HTTPException(503, '本地检索暂未就绪，请先安装检索运行环境并构建索引。')


@app.get('/api/resources/{resource_path:path}')
def resource(resource_path: str):
    allowed = ('character/avatar.png', 'character/stickers/', 'assets/ye-shunguang/')
    if resource_path != allowed[0] and not resource_path.startswith(allowed[1:]):
        raise HTTPException(404, '资源不存在。')
    root = (ROOT / 'source/resources').resolve()
    target = (root / resource_path).resolve()
    if not target.is_relative_to(root) or target.suffix.lower() not in ('.png','.jpg','.webp') or not target.is_file():
        raise HTTPException(404, '资源不存在。')
    return FileResponse(target)


from .services import router as services_router
app.include_router(services_router)


# A built frontend can be served by the backend alone; development uses Vite's proxy.
dist = ROOT / 'frontend' / 'dist'
if dist.exists():
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @app.get('/')
    def index():
        return FileResponse(dist / 'index.html')
