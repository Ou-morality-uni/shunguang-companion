"""Deterministic orchestration gates; simulated outputs do not evaluate a real model."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk, ToolMessage

from backend.app import config, feature_config, main, runtime
from backend.app.routes import chat
from backend.app.store import Store

CASES = json.loads((Path(__file__).parents[1] / 'evals/cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_agent_contract_case(case, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'store', Store(tmp_path / 'eval.sqlite3'))
    monkeypatch.setattr(runtime, 'busy', set())
    monkeypatch.setattr(runtime, 'stops', {})
    monkeypatch.setattr(runtime, 'finished', {})
    config.save_config(config.ModelConfig(llm_model='synthetic-eval', llm_api_key='synthetic-not-a-real-key'))
    feature_config.save(
        feature_config.FeatureConfig(tools=feature_config.ToolsConfig(weather_enabled=False, search_enabled=False))
    )

    class Model:
        attempts = 0

        def bind_tools(self, schemas):
            return self

        async def astream(self, messages):
            self.attempts += 1
            if case['kind'] == 'error':
                error = RuntimeError('synthetic provider body with private marker')
                error.status_code = case['status']
                raise error
            if case['kind'] == 'recover' and self.attempts == 1:
                raise httpx.ConnectError('synthetic disconnect')
            if case['kind'] == 'tool':
                if isinstance(messages[-1], ToolMessage):
                    yield AIMessageChunk(content='工具没有获准执行。')
                else:
                    yield AIMessageChunk(content='', tool_calls=[{'id': 'eval-tool', 'name': case['tool'], 'args': {}}])
                return
            yield AIMessageChunk(content=case['text'])
            if case['kind'] == 'partial':
                raise httpx.ReadError('synthetic disconnect')

    monkeypatch.setattr(chat, 'build_model', lambda _: Model())
    with TestClient(main.app) as client:
        payload = {'content': 'x' * case['input_repeat'] if 'input_repeat' in case else case['input']}
        if 'attachments' in case:
            payload['attachments'] = case['attachments']
        response = client.post('/api/chat', json=payload)
        assert response.status_code == case.get('http', 200)
        if 'http' in case:
            return
        conversations = client.get('/api/conversations').json()
        record = client.get(f'/api/conversations/{conversations[0]["id"]}/messages').json()[-1]
        assert record['status'] == case['expected']
        assert 'synthetic provider body' not in record['content']
        if 'contains' in case:
            assert case['contains'] in record['content']
        if 'starts_with' in case:
            assert record['content'].startswith(case['starts_with'])
        if case.get('tool_denied'):
            assert record['tools'] and all(item['status'] == 'error' for item in record['tools'])
        if case.get('no_sources'):
            assert record['sources'] == []
