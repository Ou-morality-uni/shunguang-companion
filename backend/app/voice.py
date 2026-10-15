"""Real TTS adapters and local-only reference preparation until explicit consent."""

import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import uuid
import wave
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse

import httpx

from . import config
from .feature_config import TTSConfig, capabilities, tts_secret
from .transport import ssl_context

MAX_AUDIO_BYTES = 20_000_000
MAX_REFERENCE_BYTES = 6_000_000
REFERENCE_LOCK = RLock()
REFERENCE_CACHE: dict = {}
PRESETS = [
    {
        'id': 'mimo',
        'name': '小米 MiMo · 参考声音克隆',
        'base_url': 'https://api.xiaomimimo.com/v1',
        'model': 'mimo-v2.5-tts-voiceclone',
        'voice': '',
        'protocol': 'mimo-chat-audio',
        'models': ['mimo-v2.5-tts-voiceclone'],
        'reference_audio': True,
        'notice': '使用所选 MP3/WAV 的声音合成新文字，需明确启用参考音频外部处理；不会改用预置音色。',
    },
    {
        'id': 'aliyun',
        'name': '阿里云 · Qwen 实时声音复刻',
        'base_url': 'https://dashscope.aliyuncs.com',
        'model': 'qwen3-tts-vc-realtime-2026-01-15',
        'voice': '',
        'models': ['qwen3-tts-vc-realtime-2026-01-15', 'qwen3-tts-vc-realtime-2025-11-27'],
        'reference_supported': True,
        'notice': '一次创建音色，之后使用音色 ID 实时合成。音色与模型、地域及账号必须匹配。',
    },
    {
        'id': 'volcengine',
        'name': '火山引擎 · 豆包声音复刻 2.0',
        'base_url': 'https://openspeech.bytedance.com',
        'model': 'seed-tts-2.0-standard',
        'voice': '',
        'models': ['seed-tts-2.0-standard'],
        'reference_supported': True,
        'notice': '先在火山控制台完成声音复刻，填写已就绪的 speaker ID；使用新版 API Key 鉴权。',
    },
]


class VoiceError(Exception):
    def __init__(self, message: str, status=502):
        self.message, self.status = message, status


async def validate_origin(base_url: str, provider: str):
    parsed = urlparse(base_url)
    if (
        parsed.scheme != 'https'
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise VoiceError('语音地址必须是无账号和查询参数的 HTTPS 地址。', 422)
    if provider in ('aliyun', 'volcengine'):
        allowed = (
            base_url == 'https://openspeech.bytedance.com'
            if provider == 'volcengine'
            else (
                base_url in ('https://dashscope.aliyuncs.com', 'https://dashscope-intl.aliyuncs.com')
                or bool(
                    re.fullmatch(r'https://[a-zA-Z0-9-]+\.(?:cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com', base_url)
                )
            )
        )
        if not allowed:
            raise VoiceError('请填写该语音厂商的官方地址，不能跨厂商发送密钥。', 422)
        return
    if provider in ('mimo', 'openai'):
        required = 'https://api.xiaomimimo.com/v1' if provider == 'mimo' else 'https://api.openai.com/v1'
        if base_url != required:
            raise VoiceError('当前厂商地址与官方预设不一致，请选择正确预设或自定义协议。', 422)
        # These are immutable, developer-owned destinations, so caller input
        # cannot redirect them to an internal host. Local proxy software may
        # map public names into 198.18/15; DNS-IP screening belongs to custom
        # endpoints. HTTPS verification and redirect refusal still apply.
        return
    try:
        addresses = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM), 5
        )
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise VoiceError('语音服务不能访问本机、局域网或保留网络地址。', 422)
    except VoiceError:
        raise
    except (OSError, asyncio.TimeoutError, ValueError):
        raise VoiceError('无法解析语音服务地址，请检查网络。')


def headers(settings: TTSConfig, secret: str):
    value = {'Authorization': f'Bearer {secret}'}
    if settings.provider == 'mimo':
        value['api-key'] = secret
    return value


def response_error(status):
    if status in (401, 403):
        raise VoiceError('语音服务鉴权或权限失败，请检查密钥及模型权限。')
    if status == 429:
        raise VoiceError('语音服务限流或额度不足，请稍后重试。')
    if status in (400, 404, 422):
        raise VoiceError('语音模型、音色或请求格式不被上游支持，请检查配置。')
    if status >= 300:
        raise VoiceError('语音服务返回错误，未取得可用音频。')


async def upstream(settings, secret, method, path, payload=None, maximum=MAX_AUDIO_BYTES):
    await validate_origin(settings.base_url, settings.provider)
    try:
        # Retry only connection establishment: no HTTP body has been sent.
        # A broken local proxy may fall back once to the same HTTPS origin.
        # Never replay a POST after response/read timeout (could double bill).
        for system_proxy in (True, False):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(settings.timeout, connect=min(settings.timeout, 8)),
                    follow_redirects=False,
                    verify=ssl_context(),
                    trust_env=system_proxy,
                ) as client:
                    async with client.stream(
                        method, settings.base_url + path, headers=headers(settings, secret), json=payload
                    ) as response:
                        response_error(response.status_code)
                        result = bytearray()
                        async for chunk in response.aiter_bytes():
                            result.extend(chunk)
                            if len(result) > maximum:
                                raise VoiceError('语音响应超过允许大小，请缩短文字或参考片段。')
                        return bytes(result), response.headers.get('content-type', '')
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if not system_proxy:
                    raise
    except VoiceError:
        raise
    except (httpx.TimeoutException, httpx.NetworkError):
        raise VoiceError('语音服务超时或网络不可达，文字聊天仍可使用。')
    except httpx.HTTPError:
        raise VoiceError('语音服务连接失败，文字聊天仍可使用。')


async def discover(settings: TTSConfig):
    if settings.provider in ('aliyun', 'volcengine'):
        preset = next(item for item in PRESETS if item['id'] == settings.provider)
        return {
            'models': [{'id': model} for model in preset['models']],
            'voices': [],
            'model_discovery': 'documented_presets',
            'voice_discovery': 'manual_voice_id',
            'capabilities': capabilities(settings),
            'notice': '以下是已适配的文档预设，不代表密钥权限验证。请填写本账号已创建的克隆音色 ID。',
        }
    secret = tts_secret(settings)
    if not secret:
        raise VoiceError('请填写语音 API 密钥，或明确选择复用同地址的小米模型密钥。', 503)
    raw, _ = await upstream(settings, secret, 'GET', '/models', maximum=2_000_000)
    try:
        data = json.loads(raw)
        models = [
            {'id': str(x['id'])}
            for x in data.get('data', [])
            if isinstance(x, dict)
            and isinstance(x.get('id'), str)
            and len(x['id']) <= 150
            and not x['id'].lower().startswith('sk-')
        ]
    except (ValueError, TypeError):
        raise VoiceError('上游没有可解析的模型发现接口，请手动填写 TTS 模型 ID。')
    models = [x for x in models if settings.provider == 'mimo' and x['id'] == 'mimo-v2.5-tts-voiceclone']
    return {
        'models': models,
        'voices': [],
        'model_discovery': 'upstream_models_api',
        'voice_discovery': 'local_reference_audio',
        'capabilities': capabilities(settings),
        'notice': '列表来自当前密钥的真实模型接口，仅显示支持本地参考音频的声音克隆模型。声音由所选本地音频决定。'
        if models
        else '上游未列出本项目已适配的参考声音克隆模型；请检查权限或填写受支持模型，不会改用预置音色。',
    }


def reference_root():
    return config.DATA_DIR / 'voice-references'


def reference_index():
    path = reference_root() / 'index.json'
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        raise VoiceError('本机参考音频清单无法读取。', 503)


def reference_path(reference_id: str) -> Path:
    if reference_id == 'ye-shunguang-original':
        return resolve_local_reference('source/resources/voice/ye-shunguang/reference-original.mp3')
    elif reference_id == 'ye-shunguang-original-video':
        path = config.ROOT / 'source/resources/voice/ye-shunguang/reference-original.mp4'
    elif re.fullmatch('[a-f0-9]{32}', reference_id):
        record = next((x for x in reference_index() if x.get('id') == reference_id), None)
        if not record or record.get('format') not in ('wav', 'mp3'):
            raise VoiceError('参考音频不存在。', 404)
        if record.get('source_kind') == 'local_path':
            return resolve_local_reference(record['path'])
        path = reference_root() / (reference_id + '.' + record['format'])
    else:
        raise VoiceError('参考音频 ID 不正确。', 404)
    if not path.is_file():
        raise VoiceError('参考音频文件不存在。', 404)
    return path


def references():
    original = config.ROOT / 'source/resources/voice/ye-shunguang/reference-original.mp3'
    records = []
    if original.is_file():
        records.append(
            {
                'id': 'ye-shunguang-original',
                'name': '叶瞬光本地参考 MP3',
                'path': 'source/resources/voice/ye-shunguang/reference-original.mp3',
                'format': 'mp3',
                'archived': True,
                'bytes': original.stat().st_size,
                'url': '/api/voice/references/ye-shunguang-original/file',
            }
        )
    records.extend({**x, 'url': f'/api/voice/references/{x["id"]}/file', 'archived': False} for x in reference_index())
    return {
        'references': records,
        'notice': '本地文件选择/校验不会发送外部服务；开启并保存参考处理后，合成才会发送所选音频。',
    }


def resolve_local_reference(value: str) -> Path:
    """Explicit local audio selection; relative paths stay in the project."""
    if not isinstance(value, str) or any(c in value for c in ('\x00', '\r', '\n')):
        raise VoiceError('请选择本机 MP3/WAV 文件；不支持网络共享或设备路径。', 422)
    value = value.strip()
    if not value or value.startswith(('\\\\', '//')):
        raise VoiceError('请选择本机 MP3/WAV 文件；不支持网络共享或设备路径。', 422)
    candidate = Path(value)
    if candidate.drive and not candidate.is_absolute():
        raise VoiceError('请填写完整绝对路径，或相对于项目根目录的路径。', 422)
    absolute = candidate.is_absolute()
    path = (candidate if absolute else config.ROOT / candidate).resolve()
    if not absolute and not path.is_relative_to(config.ROOT.resolve()):
        raise VoiceError('相对路径不能离开项目目录；其它本机文件请使用绝对路径。', 422)
    if path.suffix.lower() not in ('.mp3', '.wav'):
        raise VoiceError('参考声音仅支持 MP3 或 WAV 音频。', 422)
    if not path.is_file():
        raise VoiceError('参考音频不存在。请检查路径，它指向运行服务的电脑。', 404)
    if not 0 < path.stat().st_size <= MAX_REFERENCE_BYTES:
        raise VoiceError('参考音频需要为不超过 6 MB 的有效文件。', 422)
    validate_audio(path.read_bytes(), path.suffix.lower()[1:])
    return path


def reference_signature(value: str) -> str:
    try:
        return hashlib.sha256(resolve_local_reference(value).read_bytes()).hexdigest()
    except (VoiceError, OSError, ValueError):
        return ''


def display_reference_path(path: Path) -> str:
    return (
        path.relative_to(config.ROOT.resolve()).as_posix() if path.is_relative_to(config.ROOT.resolve()) else str(path)
    )


def inspect_reference(value: str):
    path = resolve_local_reference(value)
    data = path.read_bytes()
    audio_format = path.suffix.lower()[1:]
    duration = validate_audio(data, audio_format)
    if audio_format == 'mp3':
        try:
            probe = subprocess.run(
                [
                    ffmpeg_path(),
                    '-nostdin',
                    '-hide_banner',
                    '-protocol_whitelist',
                    'file,pipe',
                    '-i',
                    str(path),
                    '-t',
                    '0.05',
                    '-vn',
                    '-ac',
                    '1',
                    '-ar',
                    '24000',
                    '-f',
                    's16le',
                    'pipe:1',
                ],
                capture_output=True,
                timeout=15,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            if probe.returncode != 0 or not probe.stdout:
                raise VoiceError('这个 MP3 无法解码，请选择有效的语音文件。', 422)
            match = re.search(rb'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', probe.stderr)
            if match:
                duration = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
        except (OSError, subprocess.TimeoutExpired):
            raise VoiceError('参考音频检查失败或超时。', 422)
    digest = hashlib.sha256(data).hexdigest()
    identifier = hashlib.sha256((str(path) + digest).encode()).hexdigest()[:32]
    record = {
        'id': identifier,
        'name': path.name,
        'path': display_reference_path(path),
        'source_kind': 'local_path',
        'format': audio_format,
        'bytes': len(data),
        'sha256': digest,
        'duration': duration,
    }
    with REFERENCE_LOCK:
        entries = [item for item in reference_index() if item.get('id') != identifier]
        entries.append(record)
        reference_root().mkdir(parents=True, exist_ok=True)
        temporary = reference_root() / 'index.tmp'
        temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, reference_root() / 'index.json')
    return {
        **record,
        'url': f'/api/voice/references/{identifier}/file',
        'notice': '已选择并验证本机参考音频。克隆使用该文件完整音频，不截取片段、不使用预置音色；保存配置后生效。',
    }


def ffmpeg_path():
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        raise VoiceError('音轨提取缺少 imageio-ffmpeg，请按安装说明补齐依赖。', 503)


def validate_audio(data, audio_format):
    if audio_format == 'wav':
        try:
            with wave.open(io.BytesIO(data), 'rb') as audio:
                if audio.getnframes() <= 0 or audio.getnchannels() > 8 or audio.getframerate() > 192000:
                    raise ValueError('invalid wav')
                return audio.getnframes() / audio.getframerate()
        except (wave.Error, EOFError, ValueError):
            raise VoiceError('没有取得有效 WAV 音频。')
    if audio_format == 'mp3' and (data.startswith(b'ID3') or len(data) > 2 and data[0] == 255 and data[1] & 224 == 224):
        return None
    raise VoiceError('没有取得有效音频文件。')


def store_audio(data, audio_format='wav'):
    duration = validate_audio(data, audio_format)
    target = config.DATA_DIR / 'audio'
    target.mkdir(parents=True, exist_ok=True)
    audio_id = uuid.uuid4().hex
    path = target / (audio_id + '.' + audio_format)
    path.write_bytes(data)
    # Retain a bounded replay cache. Never touch original/reference files.
    retained = sorted(
        (x for x in target.glob('*') if re.fullmatch('[a-f0-9]{32}\\.(wav|mp3)', x.name)),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    for old in retained[120:]:
        old.unlink(missing_ok=True)
    return {
        'audio_url': f'/api/tts/audio/{path.name}',
        'audio_id': audio_id,
        'format': audio_format,
        'duration': duration,
        'bytes': len(data),
    }


def audio_path(name):
    if not re.fullmatch('[a-f0-9]{32}\\.(wav|mp3)', name):
        raise VoiceError('音频文件不存在。', 404)
    path = config.DATA_DIR / 'audio' / name
    if not path.is_file():
        raise VoiceError('音频已过期，请重新合成。', 404)
    return path


def prepare_reference(reference_id, start, end):
    if start < 0 or end <= start or end - start > 60:
        raise VoiceError('请选择最长 60 秒的有效参考片段。', 422)
    source = reference_path(reference_id)
    try:
        completed = subprocess.run(
            [
                ffmpeg_path(),
                '-nostdin',
                '-hide_banner',
                '-loglevel',
                'error',
                '-ss',
                str(start),
                '-i',
                str(source),
                '-t',
                str(end - start),
                '-vn',
                '-ac',
                '1',
                '-ar',
                '24000',
                '-c:a',
                'pcm_s16le',
                '-f',
                'wav',
                'pipe:1',
            ],
            capture_output=True,
            timeout=30,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        if completed.returncode != 0 or not completed.stdout or len(completed.stdout) > MAX_REFERENCE_BYTES:
            raise VoiceError('无法提取这个参考片段，请检查音轨和时间范围。', 422)
        # ffmpeg cannot seek on a pipe to repair WAV size; rewrite a finite header.
        with wave.open(io.BytesIO(completed.stdout), 'rb') as audio:
            frames, channels, rate, width = (
                audio.readframes(int((end - start) * 24000) + 1),
                audio.getnchannels(),
                audio.getframerate(),
                audio.getsampwidth(),
            )
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as out:
            out.setnchannels(channels)
            out.setsampwidth(width)
            out.setframerate(rate)
            out.writeframes(frames)
        data = buffer.getvalue()
        validate_audio(data, 'wav')
        return data
    except VoiceError:
        raise
    except (OSError, subprocess.TimeoutExpired, wave.Error, EOFError):
        raise VoiceError('参考音轨处理失败或超时，请检查文件。')


def preview(reference_id, start, end):
    return {
        **store_audio(prepare_reference(reference_id, start, end)),
        'kind': 'reference_preview',
        'notice': '这是本机参考录音片段试听，不是动态合成。',
    }


def upload_reference(name, audio_format, encoded, text=''):
    if audio_format not in ('wav', 'mp3') or len(encoded) > 8_000_000:
        raise VoiceError('本机参考上传支持不超过 6 MB 的 WAV 或 MP3。', 422)
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise VoiceError('参考音频编码不正确。', 422)
    if not data or len(data) > MAX_REFERENCE_BYTES:
        raise VoiceError('参考音频为空或超过 6 MB。', 422)
    duration = validate_audio(data, audio_format)
    reference_id = uuid.uuid4().hex
    root = reference_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / (reference_id + '.' + audio_format)).write_bytes(data)
    record = {
        'id': reference_id,
        'name': name[:100],
        'path': display_reference_path((root / (reference_id + '.' + audio_format)).resolve()),
        'format': audio_format,
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'text': text[:2000],
        'duration': duration,
    }
    with REFERENCE_LOCK:
        entries = reference_index()
        entries.append(record)
        path = root / 'index.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    return {
        **record,
        'url': f'/api/voice/references/{reference_id}/file',
        'notice': '仅保存到运行电脑，尚未发送外部服务。',
    }


def cached_reference(value: str):
    """Cache validation/probing and encoding by content, never reuse changed bytes."""
    path = resolve_local_reference(value)
    sample = path.read_bytes()
    digest = hashlib.sha256(sample).hexdigest()
    key = (str(config.DATA_DIR), str(path), digest)
    with REFERENCE_LOCK:
        if key in REFERENCE_CACHE:
            return REFERENCE_CACHE[key]
        selected = inspect_reference(value)
        if selected['sha256'] != digest:
            raise VoiceError('参考音频在检查后发生变化，请重试。', 409)
        mime = 'audio/mpeg' if selected['format'] == 'mp3' else 'audio/wav'
        result = (selected, f'data:{mime};base64,' + base64.b64encode(sample).decode('ascii'))
        REFERENCE_CACHE[key] = result
        while len(REFERENCE_CACHE) > 2:
            del REFERENCE_CACHE[next(iter(REFERENCE_CACHE))]
        return result


async def synthesize(settings: TTSConfig, text: str):
    from .tts_providers import provider_for

    async with asyncio.timeout(settings.timeout):
        return await provider_for(settings).synthesize(settings, text)


async def synthesize_mimo(settings: TTSConfig, text: str):
    if not settings.enabled:
        raise VoiceError('语音合成尚未启用，请在陪伴设置中开启。', 503)
    secret = tts_secret(settings)
    if not secret or not settings.model:
        raise VoiceError('语音尚未配置有效密钥和模型，文字聊天仍可使用。', 503)
    if not text.strip() or len(text) > 3000:
        raise VoiceError('请输入 1–3000 字的合成文字。', 422)
    if not capabilities(settings)['reference_audio']:
        raise VoiceError(
            '当前模型不支持本地参考声音克隆。请保存 mimo-v2.5-tts-voiceclone 配置；不会改用预置音色。', 422
        )
    if not settings.external_reference_enabled:
        raise VoiceError('参考音频外部处理尚未授权，请在设置中阅读说明并选择启用。', 409)
    selected, data_uri = await asyncio.to_thread(cached_reference, settings.reference_path)
    audio = {'format': 'wav', 'voice': data_uri}
    messages = []
    if settings.style:
        messages.append({'role': 'user', 'content': settings.style})
    messages.append({'role': 'assistant', 'content': text})
    raw, _ = await upstream(
        settings,
        secret,
        'POST',
        '/chat/completions',
        {'model': settings.model, 'messages': messages, 'audio': audio, 'stream': False},
        maximum=30_000_000,
    )
    try:
        encoded = json.loads(raw)['choices'][0]['message']['audio']['data']
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, KeyError, IndexError, TypeError):
        raise VoiceError('小米接口没有返回可解析的合成音频。')
    audio_format = 'wav'
    if len(data) > MAX_AUDIO_BYTES:
        raise VoiceError('合成音频过大，请缩短文字。')
    return {
        **(await asyncio.to_thread(store_audio, data, audio_format)),
        'kind': 'synthesized',
        'provider': settings.provider,
        'model': settings.model,
        'voice': 'reference_audio',
        'reference_sha256': selected['sha256'],
        'notice': '这段音频由所选参考声音克隆模型合成新文字，不是播放原录音；不表示官方角色原声。',
    }
