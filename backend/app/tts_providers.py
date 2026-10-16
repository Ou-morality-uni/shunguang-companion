"""Voice-cloning adapters. Cloud credentials and reference media stay server-side.

Persistent providers yield mono signed little-endian PCM16 at 24 kHz. Only a
successful terminal event permits caching. Cancellation closes upstream I/O;
requests are never automatically replayed after a possible billable submission.
"""

import asyncio
import base64
import io
import json
import uuid
import wave
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Protocol
from urllib.parse import quote

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from . import voice
from .feature_config import TTSConfig, tts_secret
from .transport import ssl_context

SAMPLE_RATE = 24000


class TTSProvider(Protocol):
    async def synthesize(self, settings: TTSConfig, text: str) -> dict: ...


def validate(settings: TTSConfig, text: str):
    if not settings.enabled:
        raise voice.VoiceError('请先启用语音合成。', 503)
    if not tts_secret(settings):
        raise voice.VoiceError('请保存该语音厂商的 API Key。', 503)
    if not text.strip() or len(text) > 3000:
        raise voice.VoiceError('请输入 1–3000 字的合成文字。', 422)
    if not settings.voice or not settings.model:
        raise voice.VoiceError('请填写已注册的克隆音色 ID 和对应模型。', 422)
    if settings.provider == 'aliyun' and not aliyun_model_supported(settings.model):
        raise voice.VoiceError('请选择已适配的 Qwen-Audio-TTS 或 Qwen3-TTS-VC-Realtime 克隆模型。', 422)
    if (
        settings.provider == 'aliyun'
        and settings.model in AUDIO_MODELS
        and not settings.voice.startswith(settings.model + '-')
    ):
        raise voice.VoiceError(
            '音色 ID 与当前 Qwen-Audio 模型不匹配，请从该模型的云端列表选择音色。',
            422,
            code='voice_model_mismatch',
            stage='validation',
        )


def aliyun_model_supported(model):
    return model in AUDIO_MODELS or model.startswith('qwen3-tts-vc-realtime-')


AUDIO_MODELS = ('qwen-audio-3.1-tts-flash', 'qwen-audio-3.0-tts-flash', 'qwen-audio-3.0-tts-plus')


def decode_audio(value):
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise voice.VoiceError('语音服务返回了无效音频编码。') from None
    if not data:
        raise voice.VoiceError('语音服务返回空音频。')
    return data


async def save_pcm(settings, pcm):
    if not pcm or len(pcm) % 2:
        raise voice.VoiceError('语音流为空或 PCM 数据不完整。')
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(pcm)
    return {
        **(await asyncio.to_thread(voice.store_audio, buffer.getvalue(), 'wav')),
        'kind': 'synthesized',
        'provider': settings.provider,
        'model': settings.model,
        'voice': settings.voice,
    }


class MimoProvider:
    async def synthesize(self, settings, text):
        return await voice.synthesize_mimo(settings, text)


class StreamingProvider:
    async def synthesize(self, settings, text):
        result = None
        async for event in stream_events(settings, text):
            if event['event'] == 'done':
                result = event['data']
        return result


class AliyunProvider(StreamingProvider):
    async def pcm(self, settings, text) -> AsyncIterator[bytes]:
        async with aliyun_socket(settings) as ws:

            async def send(kind, **fields):
                await ws.send(json.dumps({'event_id': uuid.uuid4().hex, 'type': kind, **fields}))

            await send(
                'session.update',
                session={
                    'voice': settings.voice,
                    'mode': 'commit',
                    'response_format': 'pcm',
                    'sample_rate': SAMPLE_RATE,
                },
            )
            committed = False
            completed = False
            async for raw in ws:
                event = json.loads(raw)
                kind = event.get('type')
                if kind == 'error':
                    from .cloud_voices import provider_error

                    raise provider_error(event.get('error', {}), 'websocket')
                if kind == 'session.updated' and not committed:
                    committed = True
                    await send('input_text_buffer.append', text=text)
                    await send('input_text_buffer.commit')
                    await send('session.finish')
                elif kind == 'response.audio.delta':
                    yield decode_audio(event.get('delta'))
                elif kind == 'response.done':
                    status = event.get('response', {}).get('status')
                    if status not in (None, 'completed'):
                        raise voice.VoiceError('百炼未完成语音合成。', code='incomplete', stage='completion')
                    completed = True
                elif kind == 'session.finished':
                    if not committed or not completed:
                        raise voice.VoiceError(
                            '百炼未确认音频完整，请重新播放。', code='incomplete', stage='completion'
                        )
                    return
            raise voice.VoiceError('阿里云语音连接提前结束，音频不完整。')


class NoRedirectConnect(connect):
    def process_redirect(self, exc):
        return exc


def connection_error(error, stage='websocket'):
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None)
    if status:
        voice.response_error(status)
    reason = str(getattr(getattr(error, 'rcvd', None), 'reason', '')).casefold()
    if 'model' in reason:
        return voice.VoiceError(
            '百炼实时服务拒绝了当前模型（Model not exist 或未获授权）。请核对模型开通状态、账号和地域；不会重复创建音色。',
            code='model_unavailable',
            stage=stage,
        )
    if 'voice' in reason or 'speaker' in reason:
        return voice.VoiceError(
            '百炼实时服务拒绝了此音色，请检查云端列表与绑定模型。', code='voice_unavailable', stage=stage
        )
    if getattr(getattr(error, 'rcvd', None), 'code', None) == 1007:
        return voice.VoiceError('百炼拒绝了会话参数，请核对克隆模型、音色和协议。', code='invalid_session', stage=stage)
    return voice.VoiceError('百炼实时连接失败，请检查网络、代理与服务地址。', code='connection', stage=stage)


@asynccontextmanager
async def aliyun_socket(settings, path=None):
    uri = settings.base_url.replace('https://', 'wss://', 1)
    uri += path or '/api-ws/v1/realtime?model=' + quote(settings.model, safe='')
    context = None
    for proxy in (True, None):
        context = NoRedirectConnect(
            uri,
            additional_headers={'Authorization': f'Bearer {tts_secret(settings)}'},
            ssl=ssl_context(),
            open_timeout=min(settings.timeout, 12),
            close_timeout=2,
            max_size=2_000_000,
            proxy=proxy,
        )
        try:
            socket = await context.__aenter__()
            break
        except (TimeoutError, OSError):
            # No application body has been sent. Only establishment can fall back.
            if proxy is None:
                raise voice.VoiceError('百炼实时握手超时或网络不可达。', code='connection', stage='handshake') from None
        except WebSocketException as error:
            raise connection_error(error, 'handshake') from None
    try:
        yield socket
    except WebSocketException as error:
        raise connection_error(error, 'session') from None
    finally:
        await context.__aexit__(None, None, None)


async def check_model(settings):
    await voice.validate_origin(settings.base_url, settings.provider)
    if settings.model in AUDIO_MODELS:
        from .aliyun_audio import check_model as check_audio_model

        return await check_audio_model(settings)
    try:
        async with asyncio.timeout(min(settings.timeout, 20)):
            async with aliyun_socket(settings) as ws:
                await ws.send(
                    json.dumps(
                        {
                            'event_id': uuid.uuid4().hex,
                            'type': 'session.update',
                            'session': {
                                'voice': settings.voice or 'probe-unregistered-voice',
                                'mode': 'commit',
                                'response_format': 'pcm',
                                'sample_rate': SAMPLE_RATE,
                            },
                        }
                    )
                )
                async for raw in ws:
                    event = json.loads(raw)
                    if event.get('type') == 'session.updated':
                        return {'ok': True, 'stage': 'session_config', 'model': settings.model}
                    if event.get('type') == 'error':
                        from .cloud_voices import provider_error

                        error = provider_error(event.get('error', {}), 'session_config')
                        if error.code == 'voice' and not settings.voice:
                            return {'ok': True, 'stage': 'model_only', 'model': settings.model}
                        raise error
        raise voice.VoiceError('百炼未确认模型会话。', code='incomplete', stage='session_config')
    except voice.VoiceError as error:
        if error.code == 'voice_unavailable' and not settings.voice:
            return {'ok': True, 'stage': 'model_only', 'model': settings.model}
        raise
    except (TimeoutError, ValueError):
        raise voice.VoiceError(
            '百炼模型检查超时或返回无效数据。', code='invalid_response', stage='session_config'
        ) from None


PROVIDERS = {'mimo': MimoProvider(), 'aliyun': AliyunProvider()}


def provider_for(settings) -> TTSProvider:
    if settings.provider not in PROVIDERS:
        raise voice.VoiceError('当前提供商未适配声音复刻，不会改用预置音色。', 422)
    if settings.provider == 'aliyun' and settings.model in AUDIO_MODELS:
        return AUDIO_PROVIDER
    return PROVIDERS[settings.provider]


async def stream_events(settings, text):
    validate(settings, text)
    adapter = provider_for(settings)
    if not isinstance(adapter, StreamingProvider):
        raise voice.VoiceError('该克隆服务不支持实时音频流，请使用分句合成。', 422)
    await voice.validate_origin(settings.base_url, settings.provider)
    pcm = bytearray()
    try:
        async with asyncio.timeout(settings.timeout):
            async with aclosing(adapter.pcm(settings, text)) as stream:
                async for chunk in stream:
                    pcm.extend(chunk)
                    if len(pcm) > voice.MAX_AUDIO_BYTES:
                        raise voice.VoiceError('语音响应过大，请缩短文字。')
                    for offset in range(0, len(chunk), 24000):
                        yield {
                            'event': 'audio',
                            'data': {
                                'pcm': base64.b64encode(chunk[offset : offset + 24000]).decode('ascii'),
                                'sample_rate': SAMPLE_RATE,
                            },
                        }
            result = await save_pcm(settings, pcm)
            yield {'event': 'done', 'data': result}
    except voice.VoiceError:
        raise
    except (TimeoutError, OSError, httpx.HTTPError, WebSocketException):
        raise voice.VoiceError('语音连接失败或超时，文字聊天仍可使用。') from None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise voice.VoiceError('语音服务返回了不完整或无效的响应。') from None


async def register_aliyun(settings, name, reference=None):
    if settings.provider != 'aliyun' or not aliyun_model_supported(settings.model):
        raise voice.VoiceError('请选择百炼支持的 Qwen 实时克隆模型创建音色。', 422)
    if not settings.external_reference_enabled:
        raise voice.VoiceError('请先允许上传参考音频并保存配置。', 409)
    secret = tts_secret(settings)
    if not secret:
        raise voice.VoiceError('请先保存阿里云语音 API Key。', 503)
    selected, data_uri = reference or await asyncio.to_thread(voice.cached_reference, settings.reference_path)
    if settings.model in AUDIO_MODELS:
        from .aliyun_audio import register

        return await register(settings, name, selected, data_uri)
    payload = {
        'model': 'qwen-voice-enrollment',
        'input': {
            'action': 'create',
            'target_model': settings.model,
            'preferred_name': name,
            'audio': {'data': data_uri},
        },
    }
    if settings.reference_text:
        payload['input']['text'] = settings.reference_text
    async with asyncio.timeout(settings.timeout):
        raw, _ = await voice.upstream(
            settings,
            secret,
            'POST',
            '/api/v1/services/audio/tts/customization',
            payload,
            maximum=2_000_000,
        )
    try:
        output = json.loads(raw)['output']
        voice_id = output['voice']
        if output.get('target_model', settings.model) != settings.model:
            raise ValueError()
        if not isinstance(voice_id, str) or not voice_id.strip() or len(voice_id) > 150:
            raise ValueError()
        return {
            'voice': voice_id,
            'model': settings.model,
            'reference_sha256': selected['sha256'],
            'fallback_mode': bool(output.get('fallback_mode')),
        }
    except (ValueError, KeyError, TypeError):
        raise voice.VoiceError('阿里云未返回有效音色 ID，请刷新云端音色列表查询；不会自动重复创建。') from None


class AliyunAudioProvider(StreamingProvider):
    async def pcm(self, settings, text):
        from .aliyun_audio import pcm

        async with aclosing(pcm(settings, text)) as stream:
            async for chunk in stream:
                yield chunk


AUDIO_PROVIDER = AliyunAudioProvider()
