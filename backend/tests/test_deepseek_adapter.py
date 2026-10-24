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
    async def send(_, request, **kwargs):
        response = handler(request)
        response.request = request
        return response

    monkeypatch.setattr(httpx.AsyncClient, 'send', send)


def test_selected_reasoning_effort_replays_reasoning_for_the_tool_continuation(monkeypatch):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert body['thinking'] == {'type': 'enabled'}
        assert body['reasoning_effort'] == 'low'
        if len(seen) == 1:
            return stream_response(
                [
                    {'delta': {'reasoning_content': 'private reasoning for tool continuation'}},
                    {
                        'delta': {
                            'tool_calls': [
                                {
                                    'index': 0,
                                    'id': 'think-call',
                                    'type': 'function',
                                    'function': {'name': 'check', 'arguments': '{}'},
                                }
                            ]
                        }
                    },
                    {'delta': {}, 'finish_reason': 'tool_calls'},
                ]
            )
        assert body['messages'][-2]['reasoning_content'] == 'private reasoning for tool continuation'
        return stream_response([{'delta': {'content': '已核对。'}}, {'delta': {}, 'finish_reason': 'stop'}])

    mocked(monkeypatch, handler)
    model = llm.build_model(config(llm_effort='low')).bind_tools(
        [{'name': 'check', 'parameters': {'type': 'object', 'properties': {}}}]
    )

    async def run():
        first = await model.ainvoke([HumanMessage(content='核对一下')])
        assert 'private reasoning' not in first.content
        answer = await model.ainvoke(
            [HumanMessage(content='核对一下'), first, ToolMessage(content='核对成功', tool_call_id='think-call')]
        )
        assert answer.content == '已核对。'

    asyncio.run(run())


@pytest.mark.parametrize(
    ('origin', 'model_id', 'control'),
    [
        ('https://api.xiaomimimo.com/v1', 'mimo-v2.5-pro', {'thinking': {'type': 'enabled'}}),
        ('https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen3.7-plus', {'enable_thinking': True}),
    ],
)
def test_supported_hybrid_models_receive_the_selected_thinking_switch(monkeypatch, origin, model_id, control):
    def handler(request):
        body = json.loads(request.content)
        assert all(body[key] == value for key, value in control.items())
        if 'xiaomimimo' in origin:
            assert body['max_completion_tokens'] == 1800
            assert 'max_tokens' not in body
        assert 'temperature' not in body
        assert 'reasoning_effort' not in body
        return stream_response([{'delta': {'content': '收到。'}}, {'delta': {}, 'finish_reason': 'stop'}])

    mocked(monkeypatch, handler)
    model = llm.build_model(config(llm_base_url=origin, llm_model=model_id, llm_effort='on'))
    assert asyncio.run(model.ainvoke('你好')).content == '收到。'


def test_official_openai_reasoning_uses_responses_with_the_selected_effort(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert str(request.url) == 'https://api.openai.com/v1/responses'
        assert body['reasoning']['effort'] == 'low'
        assert 'temperature' not in body
        assert 'max_tokens' not in body
        return httpx.Response(
            200,
            json={
                'id': 'resp-test',
                'object': 'response',
                'created_at': 1,
                'status': 'completed',
                'model': 'gpt-5.6',
                'output': [
                    {
                        'id': 'msg-test',
                        'type': 'message',
                        'status': 'completed',
                        'role': 'assistant',
                        'content': [{'type': 'output_text', 'text': '已完成。', 'annotations': []}],
                    }
                ],
            },
        )

    mocked(monkeypatch, handler)
    model = llm.build_model(config(llm_base_url='https://api.openai.com/v1', llm_model='gpt-5.6', llm_effort='low'))
    assert llm.extract_text(asyncio.run(model.ainvoke('你好')).content) == '已完成。'


def test_qwen_thinking_only_model_does_not_receive_an_unsupported_disable_switch(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert 'enable_thinking' not in body and 'thinking' not in body
        assert 'temperature' not in body
        return stream_response([{'delta': {'content': '已完成。'}}, {'delta': {}, 'finish_reason': 'stop'}])

    mocked(monkeypatch, handler)
    model = llm.build_model(
        config(llm_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', llm_model='qwen3.7-max-preview')
    )
    assert asyncio.run(model.ainvoke('你好')).content == '已完成。'


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
