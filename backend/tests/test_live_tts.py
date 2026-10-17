"""Duplex task lifecycle, browser isolation and incomplete-audio cache protection."""

import asyncio
import json
import time

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from backend.app import access, config, feature_config, services, tts_providers, voice


@pytest.fixture
def live(monkeypatch):
    model = 'qwen-audio-3.1-tts-flash'
    feature_config.save(
        feature_config.FeatureConfig(
            tts=feature_config.TTSConfig(
                provider='aliyun',
                enabled=True,
                api_key='unit-key',
                model=model,
                voice=model + '-test-123',
                base_url='https://dashscope.aliyuncs.com',
            )
        )
    )
    sent, closed = [], []

    class Socket:
        def __init__(self):
            self.events = asyncio.Queue()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(True)

        async def close(self):
            await self.events.put(None)

        async def send(self, raw):
            frame = json.loads(raw)
            sent.append(frame)
            action = frame['header']['action']
            if action == 'continue-task':
                await self.events.put(b'\x01\x00' * 2400)
                if frame['payload']['input']['text'] == 'simulate-failure':
                    await self.events.put(
                        json.dumps(
                            {
                                'header': {
                                    'task_id': frame['header']['task_id'],
                                    'event': 'task-failed',
                                    'error_code': 'ModelNotFound',
                                    'error_message': 'private-provider-detail',
                                }
                            }
                        )
                    )
            else:
                event = 'task-started' if action == 'run-task' else 'task-finished'
                await self.events.put(json.dumps({'header': {'task_id': frame['header']['task_id'], 'event': event}}))

        def __aiter__(self):
            return self

        async def __anext__(self):
            value = await self.events.get()
            if value is None:
                raise StopAsyncIteration
            return value

    monkeypatch.setattr(tts_providers, 'NoRedirectConnect', lambda *a, **kw: Socket())

    async def validate(*_):
        pass

    monkeypatch.setattr(voice, 'validate_origin', validate)
    app = FastAPI()
    app.include_router(services.router)
    with TestClient(app) as client:
        yield client, sent, closed


def test_duplex_emits_audio_before_text_finished_and_uses_one_task(live):
    client, sent, closed = live
    with client.websocket_connect('/api/tts/live') as ws:
        ws.send_json({'type': 'text', 'text': '第一句。'})
        assert ws.receive_bytes() == b'\x01\x00' * 2400
        assert not any(x['header']['action'] == 'finish-task' for x in sent)
        ws.send_json({'type': 'text', 'text': '第二句。'})
        assert ws.receive_bytes() == b'\x01\x00' * 2400
        ws.send_json({'type': 'finish'})
        result = ws.receive_json()
        assert result['type'] == 'done' and result['duration'] == 0.2
    assert [x['header']['action'] for x in sent] == ['run-task', 'continue-task', 'continue-task', 'finish-task']
    assert len({x['header']['task_id'] for x in sent}) == 1 and closed
    assert len(list(config.DATA_DIR.glob('audio/*.wav'))) == 1


def test_disconnect_cancels_upstream_without_caching_partial_audio(live):
    client, sent, _ = live
    with client.websocket_connect('/api/tts/live') as ws:
        ws.send_json({'type': 'text', 'text': '会中断。'})
        ws.receive_bytes()
    assert not list(config.DATA_DIR.glob('audio/*.wav'))
    assert not any(x['header']['action'] == 'finish-task' for x in sent)


@pytest.mark.parametrize('headers,lan', [({'origin': 'https://untrusted.example'}, False), ({}, True)])
def test_duplex_reuses_origin_and_lan_session_checks(live, monkeypatch, headers, lan):
    client, sent, _ = live
    if lan:
        monkeypatch.setenv('SHUNGUANG_LAN_MODE', '1')
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/tts/live', headers=headers):
            pass
    assert sent == []


def test_oversized_or_invalid_frames_do_not_cache(live):
    client, _, _ = live
    with client.websocket_connect('/api/tts/live') as ws:
        ws.send_json({'type': 'text', 'text': '甲' * 3001})
        result = ws.receive_json()
        assert result['type'] == 'error' and '3000' in result['message']
    assert not list(config.DATA_DIR.glob('audio/*.wav'))


def test_authenticated_lan_socket_uses_existing_session_cookie(live, monkeypatch):
    client, _, _ = live
    monkeypatch.setenv('SHUNGUANG_LAN_MODE', '1')
    monkeypatch.setattr(access, 'sessions', {'test-session': time.time() + 100})
    client.cookies.set(access.COOKIE, 'test-session')
    with client.websocket_connect('/api/tts/live', headers={'origin': 'http://testserver'}) as ws:
        ws.send_json({'type': 'text', 'text': '通过会话验证。'})
        ws.receive_bytes()
        ws.send_json({'type': 'finish'})
        assert ws.receive_json()['type'] == 'done'


def test_upstream_failure_after_pcm_is_not_cached_or_retried(live):
    client, sent, _ = live
    with client.websocket_connect('/api/tts/live') as ws:
        ws.send_json({'type': 'text', 'text': 'simulate-failure'})
        ws.receive_bytes()
        result = ws.receive_json()
        assert result['type'] == 'error'
        assert 'private-provider-detail' not in json.dumps(result)
    assert len([x for x in sent if x['header']['action'] == 'run-task']) == 1
    assert not list(config.DATA_DIR.glob('audio/*.wav'))
