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
from contextlib import aclosing
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
    if settings.provider == 'aliyun' and not settings.model.startswith('qwen3-tts-vc-realtime-'):
        raise voice.VoiceError('阿里云适配器需要 Qwen3-TTS-VC-Realtime 克隆模型。', 422)
    if settings.provider == 'volcengine' and settings.resource_id != 'seed-icl-2.0':
        raise voice.VoiceError('火山声音复刻 2.0 需要 seed-icl-2.0 资源 ID。', 422)


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
        uri = settings.base_url.replace('https://', 'wss://', 1)
        uri += '/api-ws/v1/realtime?model=' + quote(settings.model, safe='')
        # Disable redirects, including same-scheme redirects, before credentials can leave the origin.
        async with NoRedirectConnect(
            uri,
            additional_headers={'Authorization': f'Bearer {tts_secret(settings)}'},
            ssl=ssl_context(),
            open_timeout=min(settings.timeout, 8),
            close_timeout=2,
            max_size=2_000_000,
        ) as ws:

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
            async for raw in ws:
                event = json.loads(raw)
                kind = event.get('type')
                if kind == 'error':
                    raise voice.VoiceError('阿里云语音请求失败，请检查音色、模型、地域及额度。')
                if kind == 'session.updated' and not committed:
                    committed = True
                    await send('input_text_buffer.append', text=text)
                    await send('input_text_buffer.commit')
                    await send('session.finish')
                elif kind == 'response.audio.delta':
                    yield decode_audio(event.get('delta'))
                elif kind == 'response.done' and event.get('response', {}).get('status') != 'completed':
                    raise voice.VoiceError('阿里云未完成语音合成，请重试。')
                elif kind == 'session.finished':
                    return
            raise voice.VoiceError('阿里云语音连接提前结束，音频不完整。')


class NoRedirectConnect(connect):
    def process_redirect(self, exc):
        return exc


class VolcengineProvider(StreamingProvider):
    async def pcm(self, settings, text) -> AsyncIterator[bytes]:
        headers = {
            'X-Api-Key': tts_secret(settings),
            'X-Api-Resource-Id': settings.resource_id,
            'X-Api-Request-Id': str(uuid.uuid4()),
        }
        payload = {
            'req_params': {
                'text': text,
                'speaker': settings.voice,
                'model': settings.model,
                'audio_params': {'format': 'pcm', 'sample_rate': SAMPLE_RATE},
            }
        }
        async with httpx.AsyncClient(
            verify=ssl_context(),
            timeout=httpx.Timeout(settings.timeout, connect=8),
            follow_redirects=False,
        ) as client:
            async with client.stream(
                'POST',
                settings.base_url + '/api/v3/tts/unidirectional',
                headers=headers,
                json=payload,
            ) as response:
                voice.response_error(response.status_code)
                # Bound the wire response as well as decoded audio; don't let an unbroken line grow forever.
                pending = b''
                received = 0
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
                    if received > 30_000_000:
                        raise voice.VoiceError('语音响应过大，请缩短文字。')
                    pending += chunk
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        event = self.parse_line(line)
                        if event is None:
                            continue
                        if event.get('data'):
                            yield decode_audio(event['data'])
                        if event['code'] == 20000000:
                            return
                    if len(pending) > 2_000_000:
                        raise voice.VoiceError('语音响应片段过大。')
                event = self.parse_line(pending)
                if event:
                    if event.get('data'):
                        yield decode_audio(event['data'])
                    if event['code'] == 20000000:
                        return
                raise voice.VoiceError('火山语音连接提前结束，音频不完整。')

    @staticmethod
    def parse_line(line):
        line = line.strip()
        if not line or line.startswith((b'event:', b':')):
            return None
        if line.startswith(b'data:'):
            line = line[5:].strip()
        event = json.loads(line)
        if event.get('code') not in (0, 20000000):
            raise voice.VoiceError('火山语音请求失败，请检查复刻音色授权、资源 ID 及额度。')
        return event


PROVIDERS = {'mimo': MimoProvider(), 'aliyun': AliyunProvider(), 'volcengine': VolcengineProvider()}


def provider_for(settings) -> TTSProvider:
    if settings.provider not in PROVIDERS:
        raise voice.VoiceError('当前提供商未适配声音复刻，不会改用预置音色。', 422)
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


async def register_aliyun(settings, name):
    if settings.provider != 'aliyun' or not settings.model.startswith('qwen3-tts-vc-realtime-'):
        raise voice.VoiceError('仅支持为阿里云 Qwen 实时克隆模型创建音色；火山请在控制台复刻。', 422)
    if not settings.external_reference_enabled:
        raise voice.VoiceError('请先允许上传参考音频并保存配置。', 409)
    secret = tts_secret(settings)
    if not secret:
        raise voice.VoiceError('请先保存阿里云语音 API Key。', 503)
    selected, data_uri = await asyncio.to_thread(voice.cached_reference, settings.reference_path)
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
        voice_id = json.loads(raw)['output']['voice']
        if not isinstance(voice_id, str) or not voice_id.strip() or len(voice_id) > 150:
            raise ValueError()
        return {'voice': voice_id, 'model': settings.model, 'reference_sha256': selected['sha256']}
    except (ValueError, KeyError, TypeError):
        raise voice.VoiceError('阿里云未返回有效音色 ID，请在控制台查询；不会自动重复创建。') from None
