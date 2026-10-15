"""Explicit provider presets and bounded, authenticated model discovery."""

from urllib.parse import urlparse

import httpx

from .transport import ssl_context

PRESETS = [
    {'id': 'mimo', 'name': '小米 MiMo', 'base_url': 'https://api.xiaomimimo.com/v1', 'protocol': 'openai'},
    {'id': 'deepseek', 'name': 'DeepSeek · OpenAI 协议', 'base_url': 'https://api.deepseek.com', 'protocol': 'openai'},
    {
        'id': 'deepseek-anthropic',
        'name': 'DeepSeek · Anthropic 协议',
        'base_url': 'https://api.deepseek.com/anthropic',
        'protocol': 'anthropic',
    },
    {'id': 'openai', 'name': 'OpenAI', 'base_url': 'https://api.openai.com/v1', 'protocol': 'openai'},
    {'id': 'anthropic', 'name': 'Anthropic', 'base_url': 'https://api.anthropic.com', 'protocol': 'anthropic'},
    {
        'id': 'qwen',
        'name': '阿里百炼 · 中国大陆',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'protocol': 'openai',
    },
    {'id': 'siliconflow', 'name': '硅基流动', 'base_url': 'https://api.siliconflow.cn/v1', 'protocol': 'openai'},
    {'id': 'custom', 'name': '自定义兼容服务', 'base_url': '', 'protocol': 'openai'},
]


class ProviderError(Exception):
    def __init__(self, status_code=502):
        self.status_code = status_code
        super().__init__('Upstream request failed')


def endpoint(base_url, path, *, anthropic=False):
    base = base_url.rstrip('/')
    if anthropic and not base.endswith('/v1'):
        base += '/v1'
    return base + '/' + path.lstrip('/')


def headers(config):
    key = config.llm_api_key.get_secret_value()
    if config.llm_protocol == 'anthropic':
        return {'x-api-key': key, 'anthropic-version': '2023-06-01'}
    result = {'Authorization': 'Bearer ' + key}
    if urlparse(config.llm_base_url).hostname == 'api.xiaomimimo.com':
        result['api-key'] = key
    return result


async def discover(config):
    # DeepSeek exposes its canonical OpenAI models list even for Messages users.
    base = config.llm_base_url
    is_deepseek = urlparse(base).hostname == 'api.deepseek.com'
    if is_deepseek and base.endswith('/anthropic'):
        base = base[: -len('/anthropic')]
    url = endpoint(base, 'models', anthropic=config.llm_protocol == 'anthropic' and not is_deepseek)
    with_headers = headers(config)
    if is_deepseek:
        with_headers = {'Authorization': 'Bearer ' + config.llm_api_key.get_secret_value()}
    # Honor the host's proxy/CA transport configuration; model settings still come only from the UI.
    async with httpx.AsyncClient(
        timeout=min(config.llm_timeout, 20), follow_redirects=False, verify=ssl_context()
    ) as client:
        response = await client.get(url, headers=with_headers)
        if response.status_code != 200:
            raise ProviderError(response.status_code)
        if len(response.content) > 2_000_000:
            raise ProviderError()
        data = response.json()
        models = [
            {'id': item['id']}
            for item in data.get('data', [])
            if isinstance(item, dict) and isinstance(item.get('id'), str) and len(item['id']) <= 150
        ]
        if not models:
            return {'models': [], 'notice': '上游未返回可用模型列表。请确认权限，或手动填写实际模型 ID。'}
        return {'models': models[:1000], 'notice': '来自上游实际模型列表；可见模型仍可能需要独立权限。'}
