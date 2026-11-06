import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .config_files import quarantine, read_object, warnings
from .credentials import decrypt_secret, encrypt_secret

ROOT = Path(__file__).resolve().parents[2]


def server_mode() -> bool:
    value = os.environ.get('SHUNGUANG_MODE', 'desktop')
    if value not in ('desktop', 'server'):
        raise ValueError('SHUNGUANG_MODE 只允许 desktop 或 server')
    return value == 'server'


def data_directory() -> Path:
    value = os.environ.get('SHUNGUANG_DATA_DIR')
    if not value:
        return ROOT / 'data'
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('SHUNGUANG_DATA_DIR 必须是绝对路径')
    return path


DATA_DIR = data_directory()
CONFIG_LOCK = RLock()


def local_knowledge_enabled() -> bool:
    if server_mode():
        return False
    path = DATA_DIR / 'install/preferences.json'
    if not path.exists():
        return True  # Existing desktop installations retain their knowledge base.
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return isinstance(value, dict) and value.get('mode') == 'full'
    except (OSError, ValueError):
        return False  # Corrupt preferences must not launch a heavy model unexpectedly.


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    llm_base_url: str = 'https://api.deepseek.com'
    llm_model: str = ''
    llm_api_key: SecretStr = SecretStr('')
    llm_temperature: float = Field(default=0.7, ge=0, le=2)
    llm_timeout: float = Field(default=45, ge=5, le=120)
    llm_provider: str = Field(default='custom', max_length=40)
    llm_max_tokens: int = Field(default=1800, ge=128, le=8192)
    llm_context_window: int = Field(default=32768, ge=4096, le=1048576)
    llm_protocol: Literal['openai', 'anthropic'] = 'openai'
    llm_vision: Literal['unknown', 'supported', 'unsupported'] = 'unknown'
    llm_effort: Literal['default', 'off', 'on', 'low', 'medium', 'high', 'xhigh', 'max'] = 'default'

    @field_validator('llm_base_url')
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if (
            parsed.scheme not in ('http', 'https')
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError('请输入不含账号、查询参数的 HTTP(S) API 地址')
        return value.strip().rstrip('/')


def load_config() -> ModelConfig:
    # UI-saved settings are the sole source. Do not read .env or LLM_* variables.
    with CONFIG_LOCK:
        path = DATA_DIR / 'settings.json'
        if not path.exists():
            return ModelConfig()
        record = read_object(path)
        try:
            ModelConfig(**{k: v for k, v in record.items() if k != 'llm_api_key'})
            if not isinstance(record.get('api_key_encrypted', ''), str):
                raise ValueError()
            if not isinstance(record.get('profiles', []), list) or any(
                not isinstance(p, dict) for p in record.get('profiles', [])
            ):
                raise ValueError()
            for profile in record.get('profiles', []):
                identity = profile.get('id')
                if (
                    not isinstance(identity, str)
                    or len(identity) != 24
                    or any(char not in '0123456789abcdef' for char in identity)
                ):
                    raise ValueError()
                if not isinstance(profile.get('api_key_encrypted', ''), str):
                    raise ValueError()
                ModelConfig(**{key: value for key, value in profile.items() if key != 'llm_api_key'})
        except ValueError:
            record = quarantine(path)
        encrypted = record.pop('api_key_encrypted', '')
        record.pop('llm_api_key', None)  # never accept a legacy plaintext field
        record['llm_api_key'] = SecretStr(decrypt_secret(encrypted) if encrypted else '')
        if 'llm_provider' not in record and urlparse(record.get('llm_base_url', '')).hostname == 'api.xiaomimimo.com':
            record['llm_provider'] = 'mimo'
        return ModelConfig(**record)


def save_config(config: ModelConfig) -> None:
    with CONFIG_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / 'settings.json'
        temp = path.with_suffix('.tmp')
        record = config.model_dump(exclude={'llm_api_key'})
        secret = config.llm_api_key.get_secret_value()
        if secret:
            record['api_key_encrypted'] = encrypt_secret(secret)
        profiles = []
        if path.exists():
            old = read_object(path)
            profiles = old.get('profiles', [])
            if old.get('llm_model'):
                old_profile = {k: v for k, v in old.items() if k not in ('profiles', 'llm_api_key')}
                old_profile['id'] = profile_id(old.get('llm_base_url', ''), old.get('llm_protocol', 'openai'))
                profiles = [p for p in profiles if p.get('id') != old_profile['id']] + [old_profile]
        item = {**record, 'id': profile_id(config.llm_base_url, config.llm_protocol)}
        record['profiles'] = [p for p in profiles if p.get('id') != item['id']] + [item]
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
        warnings.pop(str(path), None)


def profile_id(base_url, protocol):
    return hashlib.sha256((base_url.rstrip('/') + '|' + protocol).encode()).hexdigest()[:24]


def saved_profiles():
    path = DATA_DIR / 'settings.json'
    if not path.exists():
        return []
    with CONFIG_LOCK:
        load_config()  # Validate before exposing saved profiles.
        record = read_object(path)
    if not record:
        return []
    profiles = record.get('profiles', [])
    active = {k: v for k, v in record.items() if k != 'profiles'}
    active['id'] = profile_id(record.get('llm_base_url', ''), record.get('llm_protocol', 'openai'))
    return [p for p in profiles if p.get('id') != active['id']] + [active]


def profile_config(item):
    record = {k: v for k, v in item.items() if k not in ('id', 'api_key_encrypted', 'llm_api_key')}
    record['llm_api_key'] = SecretStr(
        decrypt_secret(item['api_key_encrypted']) if item.get('api_key_encrypted') else ''
    )
    return ModelConfig(**record)


def find_saved_config(base_url, protocol):
    pid = profile_id(base_url, protocol)
    for item in saved_profiles():
        if item.get('id') == pid:
            return profile_config(item)
    # DeepSeek's two official protocols share the same key, and only these exact endpoints.
    if base_url in ('https://api.deepseek.com', 'https://api.deepseek.com/anthropic'):
        for item in saved_profiles():
            if item.get('llm_base_url') in ('https://api.deepseek.com', 'https://api.deepseek.com/anthropic'):
                return profile_config(item)
    return None


def public_config(config: ModelConfig) -> dict:
    from .model_choices import initial_effort, selectable_efforts

    return {
        'base_url': config.llm_base_url,
        'model': config.llm_model,
        'temperature': config.llm_temperature,
        'timeout': config.llm_timeout,
        'max_tokens': config.llm_max_tokens,
        'context_window': config.llm_context_window,
        'warning': warnings.get(str(DATA_DIR / 'settings.json'), ''),
        'has_api_key': bool(config.llm_api_key.get_secret_value()),
        'configured': bool(config.llm_api_key.get_secret_value() and config.llm_model.strip()),
        'provider': config.llm_provider,
        'protocol': config.llm_protocol,
        'vision': config.llm_vision,
        'effort': initial_effort(config) if config.llm_effort == 'default' else config.llm_effort,
        'efforts': selectable_efforts(config),
    }
