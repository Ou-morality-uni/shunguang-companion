"""Conversation choices reference saved credentials; browsers never submit API origins or keys."""

import json
import os
from typing import Literal
from urllib.parse import urlparse

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config


def valid_model_id(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 150
        and not any(c.isspace() for c in value)
        and not value.lower().startswith(('sk-', 'tvly-'))
    )


class ModelChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=150)
    effort: Literal['default', 'off', 'on', 'low', 'medium', 'high', 'xhigh', 'max'] = 'default'

    @field_validator('model')
    @classmethod
    def model_id(cls, value):
        if not valid_model_id(value):
            raise ValueError('模型 ID 不正确')
        return value


class ModelChoiceOut(ModelChoice):
    configured: bool
    efforts: list[str]


class ModelItem(BaseModel):
    id: str
    efforts: list[str]
    initial_effort: str = 'default'


class ConnectionOptions(BaseModel):
    id: str
    label: str
    configured: bool
    models: list[ModelItem]


def reasoning_vendor(value):
    if value.llm_protocol != 'openai':
        return None
    host = urlparse(value.llm_base_url).hostname or ''
    if host == 'api.deepseek.com':
        return 'deepseek'
    if host == 'api.xiaomimimo.com':
        return 'mimo'
    if host in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com') or host.endswith('.maas.aliyuncs.com'):
        return 'qwen'
    return None


def hybrid_vendor(value):
    vendor, model = reasoning_vendor(value), value.llm_model
    if vendor == 'mimo' and model in (
        'mimo-v2.5',
        'mimo-v2.5-pro',
        'mimo-v2.6-flash',
        'mimo-v2.6-pro',
        'mimo-v2.6-pro-ultraspeed',
    ):
        return 'mimo'
    if vendor == 'qwen' and model in (
        'qwen3.8-max',
        'qwen3.8-flash',
        'qwen3.7-max',
        'qwen3.7-plus',
        'qwen3.7-flash',
        'qwen3.6-plus',
    ):
        return 'qwen'
    return None


def responses_model(value):
    return (
        value.llm_protocol == 'openai'
        and urlparse(value.llm_base_url).hostname == 'api.openai.com'
        and value.llm_model
        in (
            'gpt-5.6',
            'gpt-6-astra',
            'gpt-6.1-sol',
            'gpt-6-sol',
            'gpt-6-luna',
        )
    )


def claude_adaptive(value):
    return (
        value.llm_protocol == 'anthropic'
        and urlparse(value.llm_base_url).hostname == 'api.anthropic.com'
        and value.llm_model
        in (
            'claude-opus-4-6',
            'claude-sonnet-4-6',
            'claude-opus-4-7',
            'claude-opus-4-8',
            'claude-opus-5',
            'claude-sonnet-5',
            'claude-opus-5-5',
            'claude-sonnet-5-5',
            'claude-haiku-5-5',
            'claude-fable-5',
            'claude-mythos-5',
            'claude-fable-5-1',
            'claude-mythos-5-1',
            'claude-mythos-preview',
        )
    )


def effort_options(value):
    if urlparse(value.llm_base_url).hostname == 'api.deepseek.com' and value.llm_model in (
        'deepseek-flash',
        'deepseek-v4-pro',
    ):
        return ['default', 'off', 'low', 'high', 'max'] if value.llm_protocol == 'openai' else ['default']
    if hybrid_vendor(value):
        return ['default', 'off', 'on']
    if responses_model(value):
        return (['default', 'off'] if value.llm_model in ('gpt-5.6', 'gpt-6-sol', 'gpt-6-luna') else ['default']) + [
            'low',
            'medium',
            'high',
            'xhigh',
            'max',
        ]
    if claude_adaptive(value):
        return (
            ['default', 'low', 'medium', 'high']
            + (
                []
                if value.llm_model in ('claude-opus-4-6', 'claude-sonnet-4-6', 'claude-mythos-preview')
                else ['xhigh']
            )
            + ['max']
        )
    return ['default']


def cached_models():
    path = config.DATA_DIR / 'model-catalog.json'
    try:
        if not path.exists() or path.stat().st_size > 2_000_000:
            return {}
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            return {}
        return {
            key: [item for item in entries[:1000] if valid_model_id(item)]
            for key, entries in value.items()
            if isinstance(entries, list)
        }
    except (OSError, ValueError):
        return {}


def selectable_efforts(value):
    supported = effort_options(value)
    levels = [level for level in supported if level not in ('default', 'on', 'off')]
    return levels or [level for level in supported if level != 'default']


def initial_effort(value):
    supported = selectable_efforts(value)
    if 'medium' in supported:
        return 'medium'
    if 'on' in supported:
        return 'on'
    if 'high' in supported:
        return 'high'
    return supported[0] if supported else 'default'


def remember_models(profile_id, models):
    with config.CONFIG_LOCK:
        catalog = cached_models()
        catalog[profile_id] = list(dict.fromkeys(item['id'] for item in models if valid_model_id(item.get('id'))))[
            :1000
        ]
        content = json.dumps(catalog, ensure_ascii=False)
        if len(content.encode('utf-8')) > 2_000_000:
            raise ValueError('模型列表缓存过大')
        path = config.DATA_DIR / 'model-catalog.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(content, encoding='utf-8')
        os.replace(temporary, path)


def model_options():
    catalog = cached_models()
    return [
        ConnectionOptions(
            id=item['id'],
            label=f'{item.get("llm_provider", "custom")} · {urlparse(item["llm_base_url"]).netloc}',
            configured=config.public_config(value)['configured'],
            models=[
                ModelItem(
                    id=mid,
                    efforts=selectable_efforts(value.model_copy(update={'llm_model': mid})),
                    initial_effort=initial_effort(value.model_copy(update={'llm_model': mid})),
                )
                for mid in dict.fromkeys([value.llm_model] + catalog.get(item['id'], []))
                if valid_model_id(mid)
            ],
        )
        for item in config.saved_profiles()
        if item.get('llm_model')
        for value in [config.profile_config(item)]
    ]


def default_choice(value=None):
    if value is None:
        value = config.load_config()
    return {
        'profile_id': config.profile_id(value.llm_base_url, value.llm_protocol),
        'model': value.llm_model,
        'effort': value.llm_effort,
    }


def choice_config(choice):
    item = next((entry for entry in config.saved_profiles() if entry['id'] == choice['profile_id']), None)
    if item is None:
        raise HTTPException(409, '该会话保存的连接已不可用，请重新选择连接。')
    value = config.profile_config(item)
    if not valid_model_id(choice['model']):
        raise HTTPException(422, '模型 ID 不正确。')
    value = value.model_copy(
        update={
            'llm_model': choice['model'],
            'llm_vision': value.llm_vision if value.llm_model == choice['model'] else 'unknown',
        }
    )
    if choice['effort'] not in effort_options(value):
        raise HTTPException(422, '该模型尚未声明此思考选项。')
    if not config.public_config(value)['configured']:
        raise HTTPException(503, '该连接尚未配置有效密钥与模型。')
    return value.model_copy(
        update={'llm_effort': initial_effort(value) if choice['effort'] == 'default' else choice['effort']}
    )


def public_choice(choice):
    value = choice_config(choice)
    effort = initial_effort(value) if choice['effort'] == 'default' else choice['effort']
    return {
        **choice,
        'effort': effort,
        'configured': config.public_config(value)['configured'],
        'efforts': selectable_efforts(value),
    }
