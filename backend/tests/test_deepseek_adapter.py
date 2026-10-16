import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.app import deepseek_adapter, llm, providers
from backend.app.config import ModelConfig


def config(**changes):
    return ModelConfig(
        **{
            'llm_base_url': 'https://api.deepseek.com',
            'llm_model': 'deepseek-flash',
            'llm_api_key': 'test-only-key',
            **changes,
        }
    )


def stream_response(frames):
    chunks = [
        json.dumps(
            {
                'id': 'test',
                'object': 'chat.completion.chunk',
                'created': 1,
                'model': 'deepseek-flash',
                'choices': [{'index': 0, **frame}],
            }
        )
        for frame in frames
    ]
    return httpx.Response(
        200,
        headers={'content-type': 'text/event-stream'},
        text=''.join('data: ' + s + '\n\n' for s in [*chunks, '[DONE]']),
    )


def mocked(monkeypatch, handler):
    original = httpx.AsyncClient

    class MockClient(original):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(deepseek_adapter.httpx, 'AsyncClient', MockClient)


def test_deepseek_fast_stream_and_tool_result_roundtrip(monkeypatch):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert str(request.url) == 'https://api.deepseek.com/chat/completions'
        assert body['thinking'] == {'type': 'disabled'}
        assert request.headers['authorization'] == 'Bearer test-only-key'
        if len(seen) == 1:
            return stream_response(
                [
                    {'delta': {'reasoning_content': 'must not appear in user text'}},
                    {
                        'delta': {
                            'tool_calls': [
                                {
                                    'index': 0,
                                    'id': 'call1',
                                    'type': 'function',
                                    'function': {'name': 'check', 'arguments': '{"nonce":'},
                                }
                            ]
                        }
                    },
                    {'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '"test"}'}}]}},
                    {'delta': {}, 'finish_reason': 'tool_calls'},
                ]
            )
        assert body['messages'][-2]['tool_calls'][0]['id'] == 'call1'
        assert body['messages'][-1] == {'role': 'tool', 'content': 'test', 'tool_call_id': 'call1'}
        assert 'reasoning_content' not in body['messages'][-2]
        return stream_response([{'delta': {'content': 'OK'}}, {'delta': {}, 'finish_reason': 'stop'}])

    mocked(monkeypatch, handler)
    model = llm.build_model(config()).bind_tools(
        [{'name': 'check', 'parameters': {'type': 'object', 'properties': {'nonce': {'type': 'string'}}}}]
    )

    async def run():
        first = await model.ainvoke([HumanMessage(content='call check')])
        assert first.tool_calls[0]['args'] == {'nonce': 'test'}
        assert not first.content
        result = await model.ainvoke(
            [HumanMessage(content='call check'), first, ToolMessage(content='test', tool_call_id='call1')]
        )
        assert result.content == 'OK'

    asyncio.run(run())


def test_incomplete_stream_is_not_success(monkeypatch):
    mocked(monkeypatch, lambda _: stream_response([{'delta': {'content': 'partial'}}]))
    with pytest.raises(providers.ProviderError) as error:
        asyncio.run(llm.build_model(config()).ainvoke('hi'))
    assert error.value.code == 'incomplete_stream'


def test_anthropic_deepseek_disables_thinking_without_changing_other_vendors():
    deepseek = llm.build_model(config(llm_protocol='anthropic', llm_base_url='https://api.deepseek.com/anthropic'))
    assert deepseek.payload('hi', True)['thinking'] == {'type': 'disabled'}
    native = llm.build_model(config(llm_protocol='anthropic', llm_base_url='https://api.anthropic.com'))
    assert 'thinking' not in native.payload('hi', True)


def test_fast_mode_serializer_keeps_text_and_tools_without_replaying_reasoning():
    result = deepseek_adapter.serialize(
        [AIMessage(content='reply', additional_kwargs={'reasoning_content': 'private'})]
    )
    assert result == [{'role': 'assistant', 'content': 'reply'}]
