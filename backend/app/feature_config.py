"""UI-owned service settings. Secrets use the same user-scoped DPAPI backend."""

import json
import os
from datetime import datetime
from threading import RLock
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from . import config
from .credentials import decrypt_secret, encrypt_secret

LOCK = RLock()


class ToolsConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    weather_enabled: bool = True
    search_enabled: bool = True
    search_provider: str = 'public'
    api_key: SecretStr = SecretStr('')
    timeout: float = Field(default=12, ge=3, le=30)

    @field_validator('search_provider')
    @classmethod
    def provider(cls, value):
        if value not in ('public', 'bing', 'wikipedia', 'tavily'):
            raise ValueError('不支持的搜索服务')
        return value


class TTSConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    auto_play: bool = False
    work_prompts: bool = True
    muted: bool = False
    provider: str = 'mimo'
    base_url: str = 'https://api.xiaomimimo.com/v1'
    model: str = 'mimo-v2.5-tts-voiceclone'
    voice: str = ''
    resource_id: str = Field(default='seed-icl-2.0', max_length=100)
    api_key: SecretStr = SecretStr('')
    use_model_key: bool = False
    timeout: float = Field(default=45, ge=5, le=90)
    speed: float = Field(default=1, ge=0.25, le=4)
    style: str = Field(default='', max_length=1000)
    reference_id: str = Field(default='ye-shunguang-original', max_length=80)
    reference_path: str = Field(default='source/resources/voice/ye-shunguang/reference-original.mp3', max_length=1024)
    reference_start: float = Field(default=0, ge=0, le=3600)
    reference_end: float = Field(default=12, gt=0, le=3600)
    reference_text: str = Field(default='', max_length=2000)
    external_reference_enabled: bool = False

    @field_validator('provider')
    @classmethod
    def provider_valid(cls, value):
        if value not in ('mimo', 'aliyun', 'volcengine', 'openai', 'custom'):
            raise ValueError('不支持的语音服务')
        return value

    @field_validator('base_url')
    @classmethod
    def url_valid(cls, value):
        value = value.strip().rstrip('/')
        parsed = urlparse(value)
        if (
            parsed.scheme != 'https'
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError('语音接口必须是无账号和查询参数的 HTTPS 地址')
        return value

    @field_validator('model', 'voice', 'resource_id')
    @classmethod
    def id_valid(cls, value):
        value = value.strip()
        if len(value) > 150 or value.lower().startswith(('sk-', 'tvly-')):
            raise ValueError('模型或音色 ID 不正确')
        return value

    @field_validator('reference_path')
    @classmethod
    def reference_path_valid(cls, value):
        if not isinstance(value, str) or not value.strip() or any(c in value for c in ('\x00', '\r', '\n')):
            raise ValueError('请输入项目相对路径或运行电脑上的绝对音频路径')
        return value.strip()


class ReminderConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    interval_minutes: int = Field(default=45, ge=1, le=480)
    quiet_start: str = '23:00'
    quiet_end: str = '07:00'
    timezone: str = 'Asia/Shanghai'
    voice: bool = False
    paused_until: str | None = None

    @field_validator('quiet_start', 'quiet_end')
    @classmethod
    def clock_valid(cls, value):
        datetime.strptime(value, '%H:%M')
        if len(value) != 5:
            raise ValueError('请输入 HH:MM 时间')
        return value

    @field_validator('timezone')
    @classmethod
    def zone_valid(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('不支持的时区，请安装 tzdata')
        return value

    @field_validator('paused_until')
    @classmethod
    def pause_valid(cls, value):
        if value is not None and datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('暂停时间需要时区')
        return value


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    auto_save: bool = True
    recall_history: bool = True


class FeatureConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    reminders: ReminderConfig = Field(default_factory=ReminderConfig)


def load() -> FeatureConfig:
    with LOCK:
        path = config.DATA_DIR / 'features.json'
        if not path.exists():
            return FeatureConfig()
        record = json.loads(path.read_text(encoding='utf-8'))
        for name in ('tools', 'tts'):
            block = record.setdefault(name, {})
            encrypted = block.pop('api_key_encrypted', '')
            block.pop('api_key', None)
            block['api_key'] = SecretStr(decrypt_secret(encrypted) if encrypted else '')
        if record.get('tts', {}).get('provider') == 'volcengine':
            record['tts'].update(
                provider='mimo',
                enabled=False,
                voice='',
                model='mimo-v2.5-tts-voiceclone',
                base_url='https://api.xiaomimimo.com/v1',
                api_key=SecretStr(''),
            )
        return FeatureConfig.model_validate(record)


def save(value: FeatureConfig) -> None:
    with LOCK:
        record = value.model_dump(exclude={'tools': {'api_key'}, 'tts': {'api_key'}})
        for name in ('tools', 'tts'):
            secret = getattr(value, name).api_key.get_secret_value()
            if secret:
                record[name]['api_key_encrypted'] = encrypt_secret(secret)
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = config.DATA_DIR / 'features.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
        cache_tts_profile(value.tts)


def cache_tts_profile(value):
    if value.provider not in ('mimo', 'aliyun'):
        return
    try:
        path = config.DATA_DIR / 'tts-profiles.json'
        profiles = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        if not isinstance(profiles, list) or any(not isinstance(p, dict) for p in profiles):
            raise ValueError('invalid profile cache')
        record = value.model_dump(exclude={'api_key'})
        if value.api_key.get_secret_value():
            record['api_key_encrypted'] = encrypt_secret(value.api_key.get_secret_value())
        profiles = [p for p in profiles if (p.get('provider'), p.get('base_url')) != (value.provider, value.base_url)]
        profiles.append(record)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError) as error:
        from .logging_setup import report_error

        report_error('tts_profile_cache', error)


def saved_tts_profile(provider, base_url):
    with LOCK:
        current = load().tts
        if (provider, base_url) == (current.provider, current.base_url):
            return current
        path = config.DATA_DIR / 'tts-profiles.json'
        profiles = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        record = next(
            (dict(p) for p in profiles if (p.get('provider'), p.get('base_url')) == (provider, base_url)), None
        )
        if record is None:
            return None
        encrypted = record.pop('api_key_encrypted', '')
        record.pop('api_key', None)
        record['api_key'] = SecretStr(decrypt_secret(encrypted) if encrypted else '')
        return TTSConfig.model_validate(record)


def tts_secret(value: TTSConfig) -> str:
    secret = value.api_key.get_secret_value()
    if secret:
        return secret
    # A saved chat key is reused only after explicit UI choice, for the exact
    # Xiaomi origin, never to an arbitrary custom endpoint.
    if value.use_model_key and value.provider == 'mimo' and value.base_url == 'https://api.xiaomimimo.com/v1':
        current = config.find_saved_config(value.base_url, 'openai')
        if current and current.llm_base_url.rstrip('/') == value.base_url:
            return current.llm_api_key.get_secret_value()
    return ''


def capabilities(value: TTSConfig) -> dict:
    from .tts_providers import aliyun_model_supported

    persistent = value.provider == 'aliyun' and aliyun_model_supported(value.model)
    return {
        'reference_audio': value.provider == 'mimo' and value.model == 'mimo-v2.5-tts-voiceclone',
        'persistent_voice': persistent,
        'streaming_audio': persistent,
        'reference_upload_local': False,
        'voice_discovery': value.provider == 'aliyun',
        'voice_id_generation': value.provider == 'aliyun',
    }


def public(value: FeatureConfig) -> dict:
    result = value.model_dump(exclude={'tools': {'api_key'}, 'tts': {'api_key'}})
    result['tools']['has_api_key'] = bool(value.tools.api_key.get_secret_value())
    result['tools']['coverage'] = {
        'public': '公开网页搜索，无需 API Key：DuckDuckGo 主查询，最多一次 Bing RSS 回退；公开服务可能限流或要求验证，不保证持续可用。',
        'bing': 'Bing 公开 RSS 网页搜索（尽力服务），无专用 API 可用性保证，结果需核对。',
        'wikipedia': '百科检索（Wikipedia），不覆盖实时新闻或整个网页',
        'tavily': 'Tavily 网页搜索，需要有效密钥',
    }[value.tools.search_provider]
    result['tts']['has_api_key'] = bool(tts_secret(value.tts))
    from .voice import reference_signature

    result['tts']['reference_sha256'] = (
        reference_signature(value.tts.reference_path) if value.tts.provider == 'mimo' else None
    )
    result['tts']['configured'] = bool(
        tts_secret(value.tts)
        and (
            (capabilities(value.tts)['persistent_voice'] and value.tts.model and value.tts.voice)
            or (
                capabilities(value.tts)['reference_audio']
                and result['tts']['reference_sha256']
                and value.tts.external_reference_enabled
            )
        )
    )
    result['tts']['capabilities'] = capabilities(value.tts)
    result['tts']['notice'] = (
        '小米每次合成提交参考音频；百炼使用已注册的云端音色 ID。不会自动切换厂商或使用预置音色兜底。'
    )
    return result


def update(patch: dict) -> FeatureConfig:
    with LOCK:
        if set(patch) - {'tools', 'tts', 'reminders', 'memory'}:
            raise ValueError('未知设置分类')
        current = load()
        record = current.model_dump()
        for name, block in patch.items():
            if not isinstance(block, dict):
                raise ValueError('设置分类必须是对象')
            block = dict(block)
            if name in ('tools', 'tts'):
                clear = block.pop('clear_api_key', False)
                submitted = block.pop('api_key', '')
                if submitted is None:
                    submitted = ''
                if not isinstance(submitted, str) or len(submitted) > 2048 or any(c.isspace() for c in submitted):
                    raise ValueError('密钥格式错误')
                if not isinstance(clear, bool) or (clear and submitted):
                    raise ValueError('移除与替换密钥不能同时进行')
                previous = getattr(current, name)
                same_origin = name != 'tts' or (
                    block.get('provider', previous.provider) == previous.provider
                    and block.get('base_url', previous.base_url).rstrip('/') == previous.base_url
                )
                if name == 'tts' and not same_origin:
                    cache_tts_profile(previous)
                saved = (
                    saved_tts_profile(
                        block.get('provider', previous.provider), block.get('base_url', previous.base_url).rstrip('/')
                    )
                    if name == 'tts' and not same_origin
                    else None
                )
                block['api_key'] = SecretStr(
                    ''
                    if clear
                    else submitted
                    or (
                        previous.api_key.get_secret_value()
                        if same_origin
                        else saved.api_key.get_secret_value()
                        if saved
                        else ''
                    )
                )
            record[name].update(block)
        if patch.get('tts', {}).get('provider') == 'volcengine':
            raise ValueError('火山语音已移除，请选择小米或百炼')
        updated = FeatureConfig.model_validate(record)
        if (
            updated.tts.reference_end <= updated.tts.reference_start
            or updated.tts.reference_end - updated.tts.reference_start > 60
        ):
            raise ValueError('参考片段需要 0–60 秒的有效范围')
        save(updated)
        return updated


# Stable integration name used by main.py.
load_features = load
