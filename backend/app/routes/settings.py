import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, ValidationError

from .. import access
from ..config import (
    CONFIG_LOCK,
    ModelConfig,
    find_saved_config,
    load_config,
    profile_config,
    public_config,
    save_config,
    saved_profiles,
)
from ..constants import VERSION
from ..llm import EmptyResponseError, build_model, extract_text, friendly_error
from ..logging_setup import report_error
from ..model_choices import (
    ConnectionOptions,
    ModelChoiceOut,
    default_choice,
    effort_options,
    model_options,
    remember_models,
)
from ..providers import PRESETS, discover
from ..runtime import require_config
from ..schemas import SettingsOut
from ..updates import UpdateCheckOut
from ..updates import check as check_update

router = APIRouter()


@router.post('/api/updates/check', response_model=UpdateCheckOut)
async def updates_check():
    return await check_update()


@router.get('/api/model-default', response_model=ModelChoiceOut | None)
def chat_model_default():
    value = load_config()
    if not value.llm_model:
        return None
    public = public_config(value)
    return {
        **default_choice(value),
        'configured': public['configured'],
        'efforts': public['efforts'],
        'effort': public['effort'],
    }


@router.get('/api/model-options', response_model=list[ConnectionOptions])
def chat_model_options():
    return model_options()


@router.post('/api/model-options/{profile_id}/refresh', response_model=ConnectionOptions)
async def refresh_chat_models(profile_id: str):
    item = next((entry for entry in saved_profiles() if entry['id'] == profile_id), None)
    if item is None:
        raise HTTPException(404, '保存的连接不存在。')
    value = profile_config(item)
    if not public_config(value)['configured']:
        raise HTTPException(503, '请先配置该连接。')
    try:
        result = await discover(value)
        await asyncio.to_thread(remember_models, profile_id, result['models'])
        return next(entry for entry in model_options() if entry.id == profile_id)
    except Exception as error:
        report_error('model_discovery', error)
        raise HTTPException(502, '模型发现失败，仍保留已保存的模型，请检查连接或稍后重试。')


class SettingsUpdate(BaseModel):
    base_url: str = Field(max_length=500)
    model: str = Field(max_length=150)
    temperature: float = Field(ge=0, le=2)
    timeout: float = Field(ge=5, le=120)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    max_tokens: int = Field(default=1800, ge=128, le=8192)
    provider: str = Field(default='custom', max_length=40)
    protocol: Literal['openai', 'anthropic'] = 'openai'
    vision: Literal['unknown', 'supported', 'unsupported'] | None = None
    effort: Literal['default', 'off', 'on', 'low', 'medium', 'high', 'xhigh', 'max'] = 'default'


class DiscoveryRequest(BaseModel):
    base_url: str = Field(max_length=500)
    provider: str = Field(default='custom', max_length=40)
    protocol: Literal['openai', 'anthropic'] = 'openai'
    api_key: SecretStr | None = None
    timeout: float = Field(default=20, ge=5, le=120)


class LoginRequest(BaseModel):
    password: SecretStr = Field(max_length=300)


@router.get('/api/auth/status')
def auth_status(request: Request):
    return {'required': access.lan_mode(), 'authenticated': access.authenticated(request)}


@router.post('/api/auth/login')
def auth_login(payload: LoginRequest, request: Request):
    return access.login(request, payload.password.get_secret_value())


@router.get('/api/health')
def health():
    return {'status': 'ok', 'version': VERSION}


@router.get('/api/settings', response_model=SettingsOut)
def settings():
    return public_config(load_config())


@router.patch('/api/settings', response_model=SettingsOut)
def update_settings(payload: SettingsUpdate):
    with CONFIG_LOCK:
        current = load_config()
        if payload.model.strip().lower().startswith('sk-'):
            raise HTTPException(422, '模型名称看起来是 API 密钥，请将密钥填写到 API 密钥栏。')
        submitted = payload.api_key.get_secret_value().strip() if payload.api_key else ''
        if len(submitted) > 2048 or any(char.isspace() for char in submitted):
            raise HTTPException(422, '密钥长度或格式不正确，请重新填写。')
        if payload.clear_api_key and submitted:
            raise HTTPException(422, '移除密钥与填写新密钥不能同时进行。')
        saved = find_saved_config(payload.base_url.rstrip('/'), payload.protocol)
        secret = '' if payload.clear_api_key else submitted or (saved.llm_api_key.get_secret_value() if saved else '')
        try:
            config = ModelConfig(
                **{
                    **current.model_dump(),
                    'llm_base_url': payload.base_url,
                    'llm_model': payload.model.strip(),
                    'llm_temperature': payload.temperature,
                    'llm_timeout': payload.timeout,
                    'llm_max_tokens': payload.max_tokens,
                    'llm_effort': payload.effort,
                    'llm_api_key': SecretStr(secret),
                    'llm_provider': payload.provider,
                    'llm_protocol': payload.protocol,
                    'llm_vision': payload.vision
                    if payload.vision is not None
                    else (
                        current.llm_vision
                        if (current.llm_base_url, current.llm_model, current.llm_protocol)
                        == (payload.base_url.rstrip('/'), payload.model.strip(), payload.protocol)
                        else 'unknown'
                    ),
                }
            )
        except ValidationError:
            raise HTTPException(422, 'API 地址格式不正确，请输入 HTTP(S) 地址。')
        if config.llm_effort not in effort_options(config):
            raise HTTPException(422, '该模型尚未声明此思考选项。')
        try:
            save_config(config)
        except (OSError, RuntimeError):
            raise HTTPException(503, '配置未保存，请检查本机凭据存储后重试。')
        return public_config(config)


@router.get('/api/providers/presets')
def provider_presets():
    return PRESETS


@router.get('/api/providers/profiles')
def provider_profiles():
    return [
        {**public_config(profile_config(item)), 'id': item['id']} for item in saved_profiles() if item.get('llm_model')
    ]


class ProfileActivate(BaseModel):
    id: str = Field(max_length=30)


@router.post('/api/providers/activate')
def provider_activate(payload: ProfileActivate):
    with CONFIG_LOCK:
        for item in saved_profiles():
            if item['id'] == payload.id:
                config = profile_config(item)
                save_config(config)
                return public_config(config)
    raise HTTPException(404, '保存的连接不存在。')


@router.post('/api/providers/discover')
async def provider_discover(payload: DiscoveryRequest):
    submitted = payload.api_key.get_secret_value().strip() if payload.api_key else ''
    if len(submitted) > 2048 or any(c.isspace() for c in submitted):
        raise HTTPException(422, '密钥格式不正确。')
    saved = find_saved_config(payload.base_url.rstrip('/'), payload.protocol)
    if not submitted and not saved:
        raise HTTPException(422, '新接口需要填写对应密钥；已有密钥只用于已保存连接。')
    try:
        config = ModelConfig(
            llm_base_url=payload.base_url,
            llm_protocol=payload.protocol,
            llm_provider=payload.provider,
            llm_api_key=submitted or saved.llm_api_key,
            llm_timeout=payload.timeout,
        )
        if not config.llm_api_key.get_secret_value():
            raise HTTPException(503, '请在 API 密钥栏填写密钥。')
        return await discover(config)
    except ValidationError:
        raise HTTPException(422, 'API 地址格式不正确。')
    except HTTPException:
        raise
    except Exception as error:
        report_error('provider', error)
        raise HTTPException(502, friendly_error(error) + ' 模型发现失败，仍可手动填写实际模型 ID。')


@router.post('/api/providers/test')
async def test_provider():
    config = await asyncio.to_thread(require_config)
    try:
        result = await build_model(config).ainvoke('请仅回复“连接成功”。')
        text = extract_text(result.content).strip()
        if not text:
            raise EmptyResponseError()
        return {'ok': True, 'message': text[:150], 'model': config.llm_model, 'protocol': config.llm_protocol}
    except Exception as error:
        report_error('provider', error)
        raise HTTPException(502, friendly_error(error))
