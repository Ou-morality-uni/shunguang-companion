import io
import wave

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import config, services


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'state')
    assert config.DATA_DIR.is_relative_to(tmp_path)
    app = FastAPI()
    app.include_router(services.router)
    with TestClient(app) as value:
        yield value


def recording():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\x00\x00' * 1600)
    return buffer.getvalue()


def test_online_recognition_returns_a_draft_without_saving_the_recording_or_exposing_the_key(client, monkeypatch):
    saved = client.patch(
        '/api/features',
        json={
            'asr': {
                'enabled': True,
                'base_url': 'https://asr.example/v1',
                'model': 'test-transcribe',
                'api_key': 'test-asr-only',
            }
        },
    )
    assert saved.status_code == 200
    assert saved.json()['asr']['configured'] is True
    assert 'test-asr-only' not in saved.text
    paths_before = set(config.DATA_DIR.rglob('*'))
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == 'https://asr.example/v1/audio/transcriptions'
        assert request.headers['authorization'] == 'Bearer test-asr-only'
        assert b'name="model"' in request.content and b'test-transcribe' in request.content
        assert b'filename="recording.wav"' in request.content
        return httpx.Response(200, json={'text': '帮我看看这份资料。'})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    result = client.post('/api/asr/transcribe', content=recording(), headers={'content-type': 'audio/wav'})
    assert result.status_code == 200
    assert result.json() == {'text': '帮我看看这份资料。'}
    assert len(calls) == 1
    assert set(config.DATA_DIR.rglob('*')) == paths_before


def test_changing_the_recognition_address_cannot_forward_a_saved_chat_key_to_another_origin(client, monkeypatch):
    config.save_config(
        config.ModelConfig(
            llm_base_url='https://saved.example/v1', llm_model='chat', llm_api_key='private-chat-test-key'
        )
    )
    pid = config.profile_id('https://saved.example/v1', 'openai')
    response = client.patch(
        '/api/features', json={'asr': {'enabled': True, 'base_url': 'https://saved.example/v1', 'profile_id': pid}}
    )
    assert response.status_code == 200 and response.json()['asr']['configured']
    called = []

    def handler(request):
        called.append(request)
        assert request.headers['authorization'] == 'Bearer private-chat-test-key'
        return httpx.Response(200, json={'text': '识别草稿'})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    assert (
        client.post('/api/asr/transcribe', content=recording(), headers={'content-type': 'audio/wav'}).json()['text']
        == '识别草稿'
    )
    changed = client.patch('/api/features', json={'asr': {'base_url': 'https://other.example/v1'}})
    assert changed.status_code == 200 and not changed.json()['asr']['configured']
    assert (
        client.post('/api/asr/transcribe', content=recording(), headers={'content-type': 'audio/wav'}).status_code
        == 503
    )
    assert len(called) == 1
    assert 'private-chat-test-key' not in (config.DATA_DIR / 'settings.json').read_text(encoding='utf-8')


def test_changing_the_address_clears_an_independent_recognition_key_but_blank_preserves_it(client):
    patch = {'asr': {'enabled': True, 'base_url': 'https://own.example/v1', 'api_key': 'independent-test-secret'}}
    assert client.patch('/api/features', json=patch).json()['asr']['has_api_key']
    assert client.patch('/api/features', json={'asr': {'api_key': ''}}).json()['asr']['has_api_key']
    changed = client.patch('/api/features', json={'asr': {'base_url': 'https://different.example/v1'}})
    assert not changed.json()['asr']['has_api_key']
    assert 'independent-test-secret' not in (config.DATA_DIR / 'features.json').read_text(encoding='utf-8')


@pytest.mark.parametrize(
    ('content', 'media', 'status'),
    [
        (b'', 'audio/wav', 422),
        (b'<html>not audio</html>', 'audio/wav', 422),
        (b'data', 'application/json', 415),
        (b'RIFF' + b'x' * (10 * 1024 * 1024), 'audio/wav', 413),
    ],
    ids=['empty', 'mismatched-format', 'unsupported-media', 'oversized'],
)
def test_invalid_or_oversized_recordings_are_rejected_before_contacting_the_service(
    client, monkeypatch, content, media, status
):
    assert (
        client.patch('/api/features', json={'asr': {'enabled': True, 'api_key': 'invalid-input-test'}}).status_code
        == 200
    )

    def fail(*args, **kwargs):
        pytest.fail('Invalid audio must not reach an upstream client')

    monkeypatch.setattr(httpx, 'AsyncClient', fail)
    result = client.post('/api/asr/transcribe', content=content, headers={'content-type': media})
    assert result.status_code == status


def test_an_upstream_error_does_not_expose_credentials_or_echo_its_private_body(client, monkeypatch):
    assert (
        client.patch('/api/features', json={'asr': {'enabled': True, 'api_key': 'private-asr-test'}}).status_code == 200
    )
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        'AsyncClient',
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text='private-asr-test provider diagnostic')
            ),
            **kwargs,
        ),
    )
    result = client.post('/api/asr/transcribe', content=recording(), headers={'content-type': 'audio/wav'})
    assert result.status_code == 502
    assert 'private-asr-test' not in result.text and 'provider diagnostic' not in result.text
    assert '认证失败' in result.json()['detail']
