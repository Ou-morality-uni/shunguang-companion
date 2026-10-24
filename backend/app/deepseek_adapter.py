"""Chat Completions for vendors requiring reasoning-content replay during tools."""

import asyncio
import json

import httpx
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai import AsyncOpenAI

from .model_choices import hybrid_vendor, reasoning_vendor
from .providers import ProviderError, headers
from .transport import ssl_context


def serialize(messages, *, include_reasoning=False):
    if isinstance(messages, str):
        messages = [HumanMessage(content=messages)]
    result = []
    for message in messages:
        if isinstance(message, SystemMessage):
            item = {'role': 'system', 'content': message.content}
        elif isinstance(message, ToolMessage):
            item = {'role': 'tool', 'content': message.content, 'tool_call_id': message.tool_call_id}
        elif isinstance(message, AIMessage):
            item = {'role': 'assistant', 'content': message.content or ''}
            if message.tool_calls:
                item['tool_calls'] = [
                    {
                        'id': call['id'],
                        'type': 'function',
                        'function': {'name': call['name'], 'arguments': json.dumps(call['args'], ensure_ascii=False)},
                    }
                    for call in message.tool_calls
                ]
            if include_reasoning and isinstance(message.additional_kwargs.get('reasoning_content'), str):
                item['reasoning_content'] = message.additional_kwargs['reasoning_content']
        else:
            item = {'role': 'user', 'content': message.content}
        result.append(item)
    return result


class DeepSeekModel:
    def __init__(self, config, tools=None):
        self.config, self.tools = config, tools or []
        self.model_name = config.llm_model

    def bind_tools(self, tools):
        return DeepSeekModel(self.config, tools)

    async def ainvoke(self, messages):
        accumulated = None
        async for chunk in self.astream(messages):
            accumulated = chunk if accumulated is None else accumulated + chunk
        if accumulated is None:
            raise ProviderError(code='empty_response')
        return AIMessage(
            content=accumulated.content,
            tool_calls=accumulated.tool_calls,
            additional_kwargs=accumulated.additional_kwargs,
        )

    async def astream(self, messages):
        vendor, hybrid = reasoning_vendor(self.config), hybrid_vendor(self.config)
        thinking = self.config.llm_effort in ('on', 'low', 'high', 'max')
        preserve_reasoning = thinking or (
            vendor in ('mimo', 'qwen') and self.config.llm_effort == 'default' and (vendor == 'mimo' or not hybrid)
        )
        payload = {
            'model': self.config.llm_model,
            'messages': serialize(messages, include_reasoning=preserve_reasoning),
            'max_tokens': self.config.llm_max_tokens,
            'temperature': self.config.llm_temperature,
            'stream': True,
            'extra_body': {'thinking': {'type': 'enabled' if thinking else 'disabled'}},
        }
        if vendor == 'qwen' and hybrid:
            payload['extra_body'] = {'enable_thinking': thinking}
        elif vendor != 'deepseek' and (self.config.llm_effort == 'default' or not hybrid):
            payload.pop('extra_body')
        if thinking and vendor == 'deepseek':
            payload['reasoning_effort'] = self.config.llm_effort
        if preserve_reasoning:
            payload.pop('temperature')
        if vendor == 'mimo':
            payload['max_completion_tokens'] = payload.pop('max_tokens')
        if self.tools:
            payload['tools'] = [convert_to_openai_tool(tool) for tool in self.tools]
        async with asyncio.timeout(self.config.llm_timeout):
            async with httpx.AsyncClient(
                verify=ssl_context(), follow_redirects=False, timeout=self.config.llm_timeout
            ) as transport:
                async with AsyncOpenAI(
                    api_key=self.config.llm_api_key.get_secret_value(),
                    base_url=self.config.llm_base_url,
                    default_headers=headers(self.config),
                    http_client=transport,
                    max_retries=0,
                ) as client:
                    stream = await client.chat.completions.create(**payload)
                    finished = False
                    try:
                        async for event in stream:
                            if not event.choices:
                                continue
                            choice = event.choices[0]
                            if choice.finish_reason:
                                finished = True
                            delta = choice.delta
                            calls = [
                                {
                                    'name': call.function.name if call.function else None,
                                    'args': call.function.arguments or '' if call.function else '',
                                    'id': call.id,
                                    'index': call.index,
                                }
                                for call in delta.tool_calls or []
                            ]
                            yield AIMessageChunk(
                                content=delta.content or '',
                                additional_kwargs={'reasoning_content': getattr(delta, 'reasoning_content', '') or ''}
                                if preserve_reasoning
                                else {},
                                tool_call_chunks=calls,
                                response_metadata={'finish_reason': choice.finish_reason}
                                if choice.finish_reason
                                else {},
                            )
                    finally:
                        await stream.close()
                    if not finished:
                        raise ProviderError(code='incomplete_stream')
