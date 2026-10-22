"""Messages protocol adapter using LangChain messages and native SSE events.

No URL-only protocol switching; tool_use/tool_result are explicitly serialized.
"""

import json
from urllib.parse import urlparse

import httpx
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from .providers import ProviderError, endpoint, headers
from .transport import ssl_context


def serialize(messages):
    if isinstance(messages, str):
        messages = [HumanMessage(content=messages)]
    system, turns = [], []
    for message in messages:
        if isinstance(message, SystemMessage):
            system.append(str(message.content))
            continue
        if isinstance(message, ToolMessage):
            role = 'user'
            blocks = [{'type': 'tool_result', 'tool_use_id': message.tool_call_id, 'content': str(message.content)}]
        elif isinstance(message, AIMessage):
            role = 'assistant'
            blocks = (
                [{'type': 'text', 'text': message.content}]
                if isinstance(message.content, str) and message.content
                else []
            )
            blocks.extend(
                {'type': 'tool_use', 'id': call['id'], 'name': call['name'], 'input': call['args']}
                for call in message.tool_calls
            )
        else:
            role = 'user'
            if isinstance(message.content, str):
                blocks = [{'type': 'text', 'text': message.content}]
            else:
                blocks = []
                for block in message.content:
                    if block.get('type') == 'text':
                        blocks.append({'type': 'text', 'text': block['text']})
                    elif block.get('type') == 'image_url':
                        url = block['image_url']['url']
                        import re

                        matched = re.fullmatch(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)', url)
                        if not matched:
                            raise ValueError('only bounded inline images are supported')
                        blocks.append(
                            {
                                'type': 'image',
                                'source': {
                                    'type': 'base64',
                                    'media_type': matched[1],
                                    'data': matched[2],
                                },
                            }
                        )
                    else:
                        raise ValueError('unsupported multimodal block')
        if not blocks:
            continue
        if turns and turns[-1]['role'] == role:
            turns[-1]['content'].extend(blocks)
        else:
            turns.append({'role': role, 'content': blocks})
    return '\n\n'.join(system), turns


class AnthropicModel:
    def __init__(self, config, tools=None):
        self.config, self.tools = config, tools or []

    def bind_tools(self, tools):
        return AnthropicModel(self.config, tools)

    def payload(self, messages, stream):
        system, turns = serialize(messages)
        result = {
            'model': self.config.llm_model,
            'max_tokens': self.config.llm_max_tokens,
            'temperature': self.config.llm_temperature,
            'system': system,
            'messages': turns,
            'stream': stream,
        }
        if urlparse(self.config.llm_base_url).hostname == 'api.deepseek.com':
            result['thinking'] = {'type': 'disabled'}
        if self.tools:
            converted = [convert_to_openai_tool(tool)['function'] for tool in self.tools]
            result['tools'] = [
                {'name': t['name'], 'description': t.get('description', ''), 'input_schema': t['parameters']}
                for t in converted
            ]
        return result

    async def ainvoke(self, messages):
        accumulated = None
        async for chunk in self.astream(messages):
            accumulated = chunk if accumulated is None else accumulated + chunk
        if accumulated is None:
            raise ProviderError()
        return AIMessage(content=accumulated.content, tool_calls=accumulated.tool_calls)

    async def astream(self, messages):
        async with httpx.AsyncClient(
            timeout=self.config.llm_timeout, follow_redirects=False, verify=ssl_context()
        ) as client:
            async with client.stream(
                'POST',
                endpoint(self.config.llm_base_url, 'messages', anthropic=True),
                headers=headers(self.config),
                json=self.payload(messages, True),
            ) as response:
                if response.status_code != 200:
                    raise ProviderError(response.status_code)
                stopped, size = False, 0
                async for line in response.aiter_lines():
                    size += len(line)
                    if size > 2_000_000:
                        raise ProviderError()
                    if not line.startswith('data:'):
                        continue
                    data = json.loads(line[5:].strip())
                    kind = data.get('type')
                    if kind == 'error':
                        raise ProviderError(529)
                    if kind == 'message_stop':
                        stopped = True
                    if kind == 'content_block_start':
                        block = data.get('content_block', {})
                        if block.get('type') == 'tool_use':
                            initial = block.get('input', {})
                            yield AIMessageChunk(
                                content='',
                                tool_call_chunks=[
                                    {
                                        'name': block['name'],
                                        'id': block['id'],
                                        'args': json.dumps(initial) if initial else '',
                                        'index': data['index'],
                                    }
                                ],
                            )
                        elif block.get('type') == 'text' and block.get('text'):
                            yield AIMessageChunk(content=block['text'])
                    if kind == 'content_block_delta':
                        delta = data.get('delta', {})
                        if delta.get('type') == 'text_delta':
                            yield AIMessageChunk(content=delta.get('text', ''))
                        elif delta.get('type') == 'input_json_delta':
                            yield AIMessageChunk(
                                content='',
                                tool_call_chunks=[
                                    {
                                        'name': None,
                                        'id': None,
                                        'args': delta.get('partial_json', ''),
                                        'index': data['index'],
                                    }
                                ],
                            )
                if not stopped:
                    raise ProviderError()
