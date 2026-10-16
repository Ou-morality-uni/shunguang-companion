"""Offline protocol, streaming, cancellation and enrollment tests. No billable requests."""

import asyncio
import base64
import json
import wave

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import config, feature_config, services, voice
from backend.app import tts_providers as tts

PCM = b'\x01\x00' * 2400


def settings(provider='aliyun', **changes):
    return feature_config.TTSConfig(
        **{
            'enabled': True,
            'provider': provider,
            'api_key': 'test-only-key',
            'base_url': 'https://openspeech.bytedance.com'
            if provider == 'volcengine'
            else 'https://dashscope.aliyuncs.com',
            'model': 'seed-tts-2.0-standard' if provider == 'volcengine' else 'qwen3-tts-vc-realtime-2026-01-15',
            'voice': 'registered-test-voice',
            **changes,
        }
    )


def fake_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )


def test_removed_volcengine_cannot_synthesize_or_be_selected():
    assert 'volcengine' not in tts.PROVIDERS
    assert {x['id'] for x in voice.PRESETS} == {'mimo', 'aliyun'}
    with pytest.raises(voice.VoiceError):
        asyncio.run(voice.synthesize(settings('volcengine'), '你好'))


def test_aliyun_websocket_handshake_and_voice_id_only(monkeypatch):
    sent, closed = [], []

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(True)

        async def send(self, value):
            sent.append(json.loads(value))

        def __aiter__(self):
            return self.events()

        async def events(self):
            yield '{"type":"session.created"}'
            yield '{"type":"session.updated"}'
            assert [item['type'] for item in sent] == [
                'session.update',
                'input_text_buffer.append',
                'input_text_buffer.commit',
                'session.finish',
            ]
            yield json.dumps({'type': 'response.audio.delta', 'delta': base64.b64encode(PCM).decode()})
            yield '{"type":"response.done","response":{"status":"completed"}}'
            yield '{"type":"session.finished"}'

    def connect(uri, **kwargs):
        assert uri == 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3-tts-vc-realtime-2026-01-15'
        assert kwargs['additional_headers'] == {'Authorization': 'Bearer test-only-key'}
        assert kwargs['ssl'] is not False
        return Socket()

    monkeypatch.setattr(tts, 'NoRedirectConnect', connect)
    result = asyncio.run(voice.synthesize(settings('aliyun'), '你好'))
    assert result['voice'] == 'registered-test-voice' and result['duration'] == 0.1
    assert sent[0]['session']['voice'] == 'registered-test-voice'
    assert 'audio' not in sent[0]['session'] and closed


def test_stream_cancellation_closes_provider_and_never_caches(monkeypatch):
    closed = []

    async def pcm(*args):
        try:
            yield PCM
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    monkeypatch.setattr(tts.PROVIDERS['aliyun'], 'pcm', pcm)

    async def run():
        stream = tts.stream_events(settings(), '你好')
        assert (await anext(stream))['event'] == 'audio'
        await stream.aclose()
        assert closed

    asyncio.run(run())
    assert not list(config.DATA_DIR.glob('audio/*.wav'))


def test_aliyun_registration_requires_consent_and_uses_saved_model(monkeypatch):
    calls = []
    monkeypatch.setattr(voice, 'cached_reference', lambda path: ({'sha256': 'test-hash'}, 'data:audio/wav;base64,AQA='))

    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == '/api/v1/services/audio/tts/customization'
        assert payload['model'] == 'qwen-voice-enrollment'
        assert payload['input']['action'] == 'create'
        assert payload['input']['target_model'] == settings('aliyun').model
        calls.append(payload)
        return httpx.Response(200, json={'output': {'voice': 'new-test-voice'}})

    fake_http(monkeypatch, handler)
    with pytest.raises(voice.VoiceError) as error:
        asyncio.run(tts.register_aliyun(settings('aliyun'), 'shunguang'))
    assert error.value.status == 409 and not calls
    result = asyncio.run(tts.register_aliyun(settings('aliyun', external_reference_enabled=True), 'shunguang'))
    assert result['voice'] == 'new-test-voice' and len(calls) == 1


@pytest.mark.parametrize(
    'provider,url',
    [
        ('aliyun', 'https://dashscope.aliyuncs.com.evil.example'),
        ('aliyun', 'https://openspeech.bytedance.com'),
        ('aliyun', 'https://dashscope.aliyuncs.com:444'),
        ('volcengine', 'https://dashscope.aliyuncs.com'),
    ],
)
def test_known_provider_rejects_credential_redirect(provider, url):
    with pytest.raises(voice.VoiceError):
        asyncio.run(voice.validate_origin(url, provider))


def test_http_stream_route_and_safe_error_event(monkeypatch):
    monkeypatch.setattr(feature_config, 'load', lambda: feature_config.FeatureConfig(tts=settings()))

    async def pcm(*args):
        yield PCM
        raise voice.VoiceError('额度不足')

    monkeypatch.setattr(tts.PROVIDERS['aliyun'], 'pcm', pcm)
    app = FastAPI()
    app.include_router(services.router)
    with TestClient(app) as client:
        response = client.post('/api/tts/stream', json={'text': '你好'})
    assert response.status_code == 200 and 'text/event-stream' in response.headers['content-type']
    assert 'event: audio' in response.text and 'event: error' in response.text
    assert 'event: done' not in response.text and 'test-only-key' not in response.text


def test_reference_encoding_cache_invalidates_on_content_change(tmp_path, monkeypatch):
    path = tmp_path / 'sample.wav'

    def write(pcm):
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(pcm)

    write(PCM)
    original = voice.inspect_reference
    calls = []

    def inspect(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(voice, 'inspect_reference', inspect)
    first = voice.cached_reference(str(path))
    assert voice.cached_reference(str(path)) is first and len(calls) == 1
    write(b'\x02\x00' * 2400)
    second = voice.cached_reference(str(path))
    assert second[0]['sha256'] != first[0]['sha256'] and len(calls) == 2


def test_disconnected_nonstream_request_cancels_synthesis(monkeypatch):
    from fastapi import HTTPException

    cancelled = []

    async def synthesize(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    class Disconnected:
        async def receive(self):
            await asyncio.sleep(0)
            return {'type': 'http.disconnect'}

    monkeypatch.setattr(voice, 'synthesize', synthesize)
    with pytest.raises(HTTPException) as error:
        asyncio.run(services.tts_synthesize(services.SynthesisRequest(text='你好'), Disconnected()))
    assert error.value.status_code == 499 and cancelled


@pytest.mark.parametrize(
    'frames',
    [
        ['{"type":"session.updated"}', '{"type":"session.finished"}'],
        ['{"type":"session.updated"}', '{"type":"response.audio.delta","delta":"invalid!"}'],
        [
            '{"type":"session.updated"}',
            '{"type":"error","error":{"code":"invalid_api_key","message":"private-secret"}}',
        ],
    ],
)
def test_bad_aliyun_frames_never_cache_incomplete_audio(monkeypatch, frames):
    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, data):
            pass

        def __aiter__(self):
            return self.events()

        async def events(self):
            for frame in frames:
                yield frame

    monkeypatch.setattr(tts, 'NoRedirectConnect', lambda *args, **kwargs: Socket())
    with pytest.raises(voice.VoiceError) as error:
        asyncio.run(voice.synthesize(settings(), '你好'))
    assert 'private-secret' not in error.value.message
    assert not list(config.DATA_DIR.glob('audio/*.wav'))


def test_model_not_exist_close_is_distinguished_from_network_failure():
    from websockets.exceptions import ConnectionClosedError
    from websockets.frames import Close

    error = tts.connection_error(ConnectionClosedError(Close(1007, 'Model not exist.'), None))
    assert error.code == 'model_unavailable'
