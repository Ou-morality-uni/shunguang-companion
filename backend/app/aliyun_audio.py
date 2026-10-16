"""Qwen-Audio-TTS inference and transient enrollment, distinct from Qwen3 realtime."""

import asyncio
import base64
import json
import re
import uuid
from contextlib import aclosing

import httpx

from . import voice
from .feature_config import tts_secret
from .transport import ssl_context


async def pcm(settings, text):
    from .cloud_voices import provider_error
    from .tts_providers import aliyun_socket

    task_id = str(uuid.uuid4())
    started = False
    async with aliyun_socket(settings, '/api-ws/v1/inference') as ws:

        async def send(action, payload):
            await ws.send(
                json.dumps(
                    {
                        'header': {'action': action, 'task_id': task_id, 'streaming': 'duplex'},
                        'payload': payload,
                    }
                )
            )

        # A system voice is used only for a no-text connectivity probe.
        probe_voice = {
            'qwen-audio-3.1-tts-flash': 'longanhuan_v3.1',
            'qwen-audio-3.0-tts-plus': 'longanlingxin',
        }.get(settings.model, 'longanfengyue')
        parameters = {
            'text_type': 'PlainText',
            'voice': settings.voice if text is not None else probe_voice,
            'format': 'pcm',
            'sample_rate': 24000,
            'rate': min(2, max(0.5, settings.speed)),
        }
        if settings.style:
            parameters['instruction'] = settings.style
        await send(
            'run-task',
            {
                'task_group': 'audio',
                'task': 'tts',
                'function': 'SpeechSynthesizer',
                'model': settings.model,
                'parameters': parameters,
                'input': {},
            },
        )
        async for raw in ws:
            if isinstance(raw, bytes):
                if not started or text is None:
                    raise voice.VoiceError('百炼返回了非预期音频。', code='invalid_response')
                yield raw
                continue
            event = json.loads(raw)
            header = event.get('header', {})
            if header.get('task_id') != task_id:
                raise voice.VoiceError('百炼返回的任务 ID 不匹配。', code='invalid_response')
            kind = header.get('event')
            if kind == 'task-failed':
                raise provider_error({'code': header.get('error_code'), 'message': header.get('error_message')}, 'task')
            if kind == 'task-started' and not started:
                started = True
                if text is not None:
                    await send('continue-task', {'input': {'text': text}})
                await send('finish-task', {'input': {}})
                if text is None:
                    # A task has accepted this model. An empty finish may be
                    # rejected as "no valid text"; that is not a model failure.
                    return
            elif kind == 'task-finished':
                if not started:
                    raise voice.VoiceError('百炼未确认任务启动。', code='incomplete')
                return
        raise voice.VoiceError('百炼任务提前结束，音频不完整。', code='incomplete')


async def check_model(settings):
    try:
        async with asyncio.timeout(min(settings.timeout, 25)):
            async with aclosing(pcm(settings, None)) as stream:
                async for _ in stream:
                    pass
        return {
            'ok': True,
            'stage': 'connection_only',
            'model': settings.model,
            'synthesis_verified': False,
            'message': '百炼连接已建立。任务启动不代表模型和克隆音色可合成，请创建匹配音色并完成短句试听。',
        }
    except (TimeoutError, ValueError, TypeError):
        raise voice.VoiceError('百炼模型检查超时或响应无效。', code='invalid_response', stage='model_check') from None


async def upload_reference(settings, data_uri):
    """Use private, model-bound 48-hour OSS storage; never archive audio locally."""
    raw, _ = await voice.upstream(
        settings,
        tts_secret(settings),
        'GET',
        '/api/v1/uploads?action=getPolicy&model=voice-enrollment',
        maximum=100_000,
    )
    try:
        policy = json.loads(raw)['data']
        host = policy['upload_host']
        if not re.fullmatch(r'https://[a-zA-Z0-9-]+\.oss-(?:cn-beijing|ap-southeast-1)\.aliyuncs\.com', host):
            raise ValueError()
        directory = policy['upload_dir']
        if not re.fullmatch(r'[a-zA-Z0-9_/-]+', directory) or '..' in directory:
            raise ValueError()
        if policy['x_oss_object_acl'] != 'private' or policy['x_oss_forbid_overwrite'] != 'true':
            raise ValueError()
        mime, encoded = data_uri.split(';base64,', 1)
        data = base64.b64decode(encoded, validate=True)
        extension = 'mp3' if mime == 'data:audio/mpeg' else 'wav'
        key = directory + '/' + uuid.uuid4().hex + '.' + extension
        fields = {
            'OSSAccessKeyId': policy['oss_access_key_id'],
            'Signature': policy['signature'],
            'policy': policy['policy'],
            'x-oss-object-acl': 'private',
            'x-oss-forbid-overwrite': 'true',
            'key': key,
            'success_action_status': '200',
        }
    except (KeyError, ValueError, TypeError):
        raise voice.VoiceError('百炼未返回安全有效的临时上传凭证。', code='upload_policy', stage='upload') from None
    # Only scoped temporary OSS credentials go to OSS; never the Bailian API key.
    try:
        async with httpx.AsyncClient(timeout=settings.timeout, verify=ssl_context(), follow_redirects=False) as client:
            async with client.stream(
                'POST', host, data=fields, files={'file': ('reference.' + extension, data, mime[5:])}
            ) as response:
                if response.status_code != 200:
                    raise voice.VoiceError('百炼临时音频上传失败，尚未提交音色创建。', code='upload', stage='upload')
    except httpx.HTTPError:
        raise voice.VoiceError('百炼临时上传连接失败，尚未提交音色创建。', code='connection', stage='upload') from None
    return 'oss://' + key


async def register(settings, name, selected, data_uri):
    from .cloud_voices import provider_error

    try:
        async with asyncio.timeout(settings.timeout):
            url = await upload_reference(settings, data_uri)
    except voice.VoiceError as error:
        error.stage = 'upload'
        raise
    except TimeoutError:
        raise voice.VoiceError('百炼临时上传超时，尚未创建音色。', code='connection', stage='upload') from None
    async with asyncio.timeout(settings.timeout):
        raw, _ = await voice.upstream(
            settings,
            tts_secret(settings),
            'POST',
            '/api/v1/services/audio/tts/customization',
            {
                'model': 'voice-enrollment',
                'input': {
                    'action': 'create_voice',
                    'target_model': settings.model,
                    'prefix': name,
                    'url': url,
                    'language_hints': ['zh'],
                },
            },
            maximum=100_000,
            extra_headers={'X-DashScope-OssResourceResolve': 'enable'},
        )
    try:
        result = json.loads(raw)
        if result.get('code'):
            error = provider_error(result, 'enrollment')
            error.retry_safe = error.code in ('authentication', 'reference_url', 'reference_audio', 'model', 'voice')
            raise error
        voice_id = result['output']['voice_id']
        if not isinstance(voice_id, str) or not voice_id.startswith(settings.model + '-') or len(voice_id) > 150:
            raise ValueError()
        return {'voice': voice_id, 'model': settings.model, 'reference_sha256': selected['sha256']}
    except (ValueError, KeyError, TypeError):
        raise voice.VoiceError('创建结果未能确认，请刷新云端列表，勿重复创建。', code='invalid_response') from None
