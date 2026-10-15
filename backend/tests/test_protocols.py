import asyncio
import json

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend.app import anthropic_adapter, providers
from backend.app.config import ModelConfig


def test_anthropic_tool_messages_are_native():
    system, turns = anthropic_adapter.serialize(
        [
            SystemMessage(content='rule'),
            HumanMessage(content='weather?'),
            AIMessage(content='', tool_calls=[{'id': 'call1', 'name': 'weather', 'args': {'city': '上海'}}]),
            ToolMessage(content='actual result', tool_call_id='call1'),
            HumanMessage(content='thanks'),
        ]
    )
    assert system == 'rule'
    assert turns[1]['content'][0] == {'type': 'tool_use', 'id': 'call1', 'name': 'weather', 'input': {'city': '上海'}}
    assert turns[2]['content'][0]['type'] == 'tool_result'
    assert turns[2]['content'][0]['tool_use_id'] == 'call1'
    assert len(turns[2]['content']) == 2


def test_anthropic_native_sse_text_and_tool_delta(monkeypatch):
    seen = []
    events = [
        {'type': 'message_start', 'message': {'content': []}},
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': '查询'}},
        {
            'type': 'content_block_start',
            'index': 1,
            'content_block': {'type': 'tool_use', 'id': 'tool1', 'name': 'weather', 'input': {}},
        },
        {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'input_json_delta', 'partial_json': '{"city":'}},
        {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'input_json_delta', 'partial_json': '"上海"}'}},
        {'type': 'message_stop'},
    ]

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            text='\n\n'.join('data: ' + json.dumps(e, ensure_ascii=False) for e in events),
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        anthropic_adapter.httpx,
        'AsyncClient',
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    model = anthropic_adapter.AnthropicModel(
        ModelConfig(
            llm_base_url='https://api.deepseek.com/anthropic',
            llm_protocol='anthropic',
            llm_model='test',
            llm_api_key='protocol-test-key',
        )
    ).bind_tools(
        [
            {
                'name': 'weather',
                'description': 'actual weather',
                'parameters': {'type': 'object', 'properties': {'city': {'type': 'string'}}},
            }
        ]
    )
    result = asyncio.run(model.ainvoke([SystemMessage(content='rule'), HumanMessage(content='hi')]))
    assert result.content == '查询'
    assert result.tool_calls[0]['args'] == {'city': '上海'}
    request = seen[0]
    assert str(request.url) == 'https://api.deepseek.com/anthropic/v1/messages'
    assert request.headers['x-api-key'] == 'protocol-test-key'
    payload = json.loads(request.content)
    assert payload['tools'][0]['input_schema']['type'] == 'object'
    assert 'protocol-test-key' not in request.url.query.decode()


def test_discovery_deepseek_uses_canonical_list(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'data': [{'id': 'real-upstream-id'}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    config = ModelConfig(
        llm_base_url='https://api.deepseek.com/anthropic', llm_protocol='anthropic', llm_api_key='test-key'
    )
    result = asyncio.run(providers.discover(config))
    assert result['models'] == [{'id': 'real-upstream-id'}]
    assert str(seen[0].url) == 'https://api.deepseek.com/models'
