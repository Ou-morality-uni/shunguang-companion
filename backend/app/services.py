"""Feature routes mounted beneath the app's common access protection."""

import asyncio
import json
from contextlib import aclosing

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from . import feature_config, reminders, tools, voice

router = APIRouter()
SYNTHESIS_SLOTS = asyncio.Semaphore(2)


class FeaturePatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tools: dict | None = None
    tts: dict | None = None
    reminders: dict | None = None


@router.get('/api/features')
def features_get():
    try:
        return feature_config.public(feature_config.load())
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(503, '服务设置或本机凭据无法读取，请检查运行账户和数据目录。')


@router.patch('/api/features')
def features_patch(payload: FeaturePatch):
    try:
        result = feature_config.update(payload.model_dump(exclude_none=True))
        if payload.reminders is not None:
            reminders.reset()
        return feature_config.public(result)
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(422, '服务设置格式不正确，请检查字段、时间、地址及范围。')
    except (OSError, RuntimeError):
        raise HTTPException(503, '服务设置未保存，请检查本机加密凭据和目录权限。')


@router.get('/api/tts/presets')
def tts_presets():
    return voice.PRESETS


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: str = Field(default='mimo', max_length=30)
    base_url: str = Field(default='https://api.xiaomimimo.com/v1', max_length=500)
    api_key: SecretStr | None = None
    use_model_key: bool = False
    model: str | None = Field(default=None, max_length=150)
    voice: str | None = Field(default=None, max_length=150)


@router.post('/api/tts/discover')
async def tts_discover(payload: DiscoveryRequest):
    try:
        current = feature_config.load().tts
        secret = payload.api_key.get_secret_value() if payload.api_key else ''
        same_origin = current.provider == payload.provider and current.base_url == payload.base_url.rstrip('/')
        if not secret and same_origin:
            secret = current.api_key.get_secret_value()
        if len(secret) > 2048 or any(c.isspace() for c in secret):
            raise ValueError('invalid credential')
        value = feature_config.TTSConfig(
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=SecretStr(secret),
            use_model_key=payload.use_model_key,
            model=payload.model or '',
            voice=payload.voice or '',
        )
        return await voice.discover(value)
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)
    except (ValueError, RuntimeError, OSError):
        raise HTTPException(422, '语音发现配置无效或凭据无法读取。')


class SynthesisRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=3000)


@router.post('/api/tts/synthesize')
async def tts_synthesize(payload: SynthesisRequest, request: Request):
    async def synthesize():
        async with SYNTHESIS_SLOTS:
            return await voice.synthesize(feature_config.load().tts, payload.text)

    async def disconnected():
        # FastAPI has already consumed the JSON body. Await the disconnect event
        # directly: is_disconnected() uses a cancel scope that can swallow the
        # watcher's cancellation and keep an otherwise finished request alive.
        while (await request.receive())['type'] != 'http.disconnect':
            pass

    task = asyncio.create_task(synthesize())
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
        if task not in done:
            raise HTTPException(499, '语音请求已取消。')
        return task.result()
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, '语音合成失败，文字聊天仍可使用。')
    finally:
        for pending in (task, watcher):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


@router.post('/api/tts/stream')
async def tts_stream(payload: SynthesisRequest):
    from . import tts_providers

    settings = feature_config.load().tts
    try:
        tts_providers.validate(settings, payload.text)
        await voice.validate_origin(settings.base_url, settings.provider)
        if not feature_config.capabilities(settings)['streaming_audio']:
            raise voice.VoiceError('当前克隆服务不支持实时音频流。', 422)
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)

    async def events():
        try:
            async with SYNTHESIS_SLOTS, aclosing(tts_providers.stream_events(settings, payload.text)) as stream:
                async for event in stream:
                    yield f'event: {event["event"]}\ndata: {json.dumps(event["data"])}\n\n'
        except voice.VoiceError as error:
            yield f'event: error\ndata: {json.dumps({"message": error.message})}\n\n'
        except Exception:
            yield 'event: error\ndata: {"message":"语音流中断，文字聊天仍可使用。"}\n\n'

    return StreamingResponse(
        events(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-store',
            'X-Accel-Buffering': 'no',
        },
    )


class VoiceRegistration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(default='shunguang', pattern=r'^[A-Za-z0-9_]{1,16}$')


@router.post('/api/tts/register')
async def tts_register(payload: VoiceRegistration):
    from .tts_providers import register_aliyun

    try:
        return await register_aliyun(feature_config.load().tts, payload.name)
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)
    except Exception:
        raise HTTPException(502, '音色创建未能确认成功，请先在厂商控制台查询，避免重复创建。')


@router.get('/api/tts/audio/{name}')
def tts_audio(name: str):
    try:
        path = voice.audio_path(name)
        return FileResponse(
            path,
            media_type='audio/wav' if path.suffix == '.wav' else 'audio/mpeg',
            headers={'Cache-Control': 'private, no-store'},
        )
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)


@router.get('/api/voice/references')
def voice_references():
    try:
        return voice.references()
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)


@router.get('/api/voice/references/{reference_id}/file')
def reference_file(reference_id: str):
    try:
        path = voice.reference_path(reference_id)
        mime = {'.mp4': 'video/mp4', '.wav': 'audio/wav', '.mp3': 'audio/mpeg'}[path.suffix.lower()]
        return FileResponse(path, media_type=mime, headers={'Cache-Control': 'private, no-store'})
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reference_id: str = Field(default='ye-shunguang-original', max_length=80)
    start: float = Field(default=0, ge=0, le=3600)
    end: float = Field(default=12, gt=0, le=3600)


class LocalReferenceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=1024)


@router.post('/api/voice/reference/inspect')
async def inspect_local_reference(payload: LocalReferenceRequest):
    try:
        return await asyncio.to_thread(voice.inspect_reference, payload.path)
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)
    except (OSError, ValueError):
        raise HTTPException(422, '本机参考音频无法读取，请检查路径和文件权限。')


@router.post('/api/voice/preview')
async def reference_preview(payload: PreviewRequest):
    try:
        return await asyncio.to_thread(voice.preview, payload.reference_id, payload.start, payload.end)
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)


class ReferenceUpload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    format: str = Field(max_length=10)
    audio_base64: str = Field(min_length=1, max_length=8_000_000)
    text: str = Field(default='', max_length=2000)


@router.post('/api/voice/references/upload', status_code=201)
async def reference_upload(payload: ReferenceUpload):
    try:
        return await asyncio.to_thread(
            voice.upload_reference, payload.name, payload.format, payload.audio_base64, payload.text
        )
    except voice.VoiceError as error:
        raise HTTPException(error.status, error.message)
    except OSError:
        raise HTTPException(503, '参考音频无法保存到本机。')


@router.get('/api/reminders/poll')
def reminders_poll():
    try:
        return reminders.poll()
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(503, '提醒状态无法读取或保存，请检查数据目录。')


@router.post('/api/reminders/test')
def reminders_test():
    try:
        return reminders.poll(immediate=True)
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(503, '提醒状态无法读取或保存，请检查数据目录。')


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(max_length=30)
    args: dict = Field(default_factory=dict)


@router.post('/api/tools/run')
async def tools_run(payload: ToolRequest):
    return await tools.execute(payload.name, payload.args)
