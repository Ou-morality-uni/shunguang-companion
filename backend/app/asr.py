"""Bounded online transcription. Audio stays in memory for this request only."""

import asyncio
import json

import httpx
from fastapi import HTTPException

from . import feature_config
from .constants import MAX_MESSAGE_LENGTH
from .transport import ssl_context

MAX_AUDIO_BYTES = 10 * 1024 * 1024
SLOTS = asyncio.Semaphore(2)


async def transcribe(request):
    try:
        value = await asyncio.to_thread(lambda: feature_config.load().asr)
        secret = await asyncio.to_thread(feature_config.asr_secret, value)
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(503, '语音识别配置或本机凭据暂不可读。')
    if not value.enabled or not value.model or not secret:
        raise HTTPException(503, '请先在语音设置中启用并配置在线语音识别。')
    media = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    extensions = {'audio/webm': 'webm', 'audio/mp4': 'mp4', 'audio/wav': 'wav', 'audio/x-wav': 'wav'}
    if media not in extensions:
        raise HTTPException(415, '支持 WebM、MP4 或 WAV 录音。')
    data = bytearray()
    try:
        async with asyncio.timeout(20):
            async for chunk in request.stream():
                if len(data) + len(chunk) > MAX_AUDIO_BYTES:
                    raise HTTPException(413, '录音超过 10 MiB，请缩短后重试。')
                data.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, '录音上传超时，请重试。')
    valid = (
        (media == 'audio/webm' and data[:4] == b'\x1aE\xdf\xa3')
        or (media == 'audio/mp4' and data[4:8] == b'ftyp')
        or (media in ('audio/wav', 'audio/x-wav') and data[:4] == b'RIFF' and data[8:12] == b'WAVE')
    )
    if len(data) < 16 or not valid:
        raise HTTPException(422, '录音内容为空或格式与声明不一致。')
    try:
        async with asyncio.timeout(value.timeout), SLOTS:
            async with httpx.AsyncClient(timeout=value.timeout, follow_redirects=False, verify=ssl_context()) as client:
                async with client.stream(
                    'POST',
                    value.base_url + '/audio/transcriptions',
                    headers={'Authorization': 'Bearer ' + secret},
                    data={'model': value.model, 'response_format': 'json'},
                    files={'file': ('recording.' + extensions[media], bytes(data), media)},
                ) as response:
                    if response.status_code != 200:
                        if response.status_code in (401, 403):
                            raise HTTPException(502, '语音识别认证失败，请检查识别服务的密钥与权限。')
                        raise HTTPException(502, '语音识别服务暂不可用，请检查模型、接口或额度后重试。')
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 128_000:
                            raise HTTPException(502, '语音识别返回内容过大。')
        result = json.loads(payload)
        text = result.get('text') if isinstance(result, dict) else None
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_MESSAGE_LENGTH:
            raise HTTPException(502, '未取得有效识别文字，或文字超过输入框上限，请缩短录音后重试。')
        return text.strip()
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(502, '语音识别连接中断或超时，请稍后重试。')
    except (ValueError, UnicodeError):
        raise HTTPException(502, '语音识别返回格式不正确。')
