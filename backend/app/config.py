import json
import os
import hashlib
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .credentials import decrypt_secret, encrypt_secret

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data'
CONFIG_LOCK = RLock()


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')
    llm_base_url: str = 'https://api.deepseek.com'
    llm_model: str = ''
    llm_api_key: SecretStr = SecretStr('')
    llm_temperature: float = Field(default=0.7, ge=0, le=2)
    llm_timeout: float = Field(default=45, ge=5, le=120)
    llm_provider: str = Field(default='custom', max_length=40)
    llm_protocol: Literal['openai', 'anthropic'] = 'openai'

    @field_validator('llm_base_url')
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('请输入不含账号、查询参数的 HTTP(S) API 地址')
        return value.strip().rstrip('/')


def load_config() -> ModelConfig:
    # UI-saved settings are the sole source. Do not read .env or LLM_* variables.
    with CONFIG_LOCK:
        path = DATA_DIR / 'settings.json'
        if not path.exists():
            return ModelConfig()
        record = json.loads(path.read_text(encoding='utf-8'))
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
            old = json.loads(path.read_text(encoding='utf-8'))
            profiles = old.get('profiles', [])
            if old.get('llm_model'):
                old_profile = {k:v for k,v in old.items() if k not in ('profiles','llm_api_key')}
                old_profile['id'] = profile_id(old.get('llm_base_url', ''), old.get('llm_protocol','openai'))
                profiles = [p for p in profiles if p.get('id') != old_profile['id']] + [old_profile]
        item = {**record, 'id': profile_id(config.llm_base_url, config.llm_protocol)}
        record['profiles'] = [p for p in profiles if p.get('id') != item['id']] + [item]
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)


def profile_id(base_url, protocol):
    return hashlib.sha256((base_url.rstrip('/') + '|' + protocol).encode()).hexdigest()[:24]


def saved_profiles():
    path = DATA_DIR / 'settings.json'
    if not path.exists():
        return []
    record = json.loads(path.read_text(encoding='utf-8'))
    profiles = record.get('profiles', [])
    active = {k:v for k,v in record.items() if k != 'profiles'}
    active['id'] = profile_id(record.get('llm_base_url',''), record.get('llm_protocol','openai'))
    return [p for p in profiles if p.get('id') != active['id']] + [active]


def profile_config(item):
    record = {k:v for k,v in item.items() if k not in ('id','api_key_encrypted','llm_api_key')}
    record['llm_api_key'] = SecretStr(decrypt_secret(item['api_key_encrypted']) if item.get('api_key_encrypted') else '')
    return ModelConfig(**record)


def find_saved_config(base_url, protocol):
    pid = profile_id(base_url, protocol)
    for item in saved_profiles():
        if item.get('id') == pid:
            return profile_config(item)
    # DeepSeek's two official protocols share the same key, and only these exact endpoints.
    if base_url in ('https://api.deepseek.com','https://api.deepseek.com/anthropic'):
        for item in saved_profiles():
            if item.get('llm_base_url') in ('https://api.deepseek.com','https://api.deepseek.com/anthropic'):
                return profile_config(item)
    return None


def public_config(config: ModelConfig) -> dict:
    return {
        'base_url': config.llm_base_url,
        'model': config.llm_model,
        'temperature': config.llm_temperature,
        'timeout': config.llm_timeout,
        'has_api_key': bool(config.llm_api_key.get_secret_value()),
        'configured': bool(config.llm_api_key.get_secret_value() and config.llm_model.strip()),
        'provider': config.llm_provider,
        'protocol': config.llm_protocol,
    }
