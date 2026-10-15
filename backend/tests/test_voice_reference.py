"""Local reference selection and clone contracts; no real cloud requests."""

import base64
import hashlib
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import config, services, voice


def sample():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b'\x08\x00' * 2400)
    return buffer.getvalue()


@pytest.fixture
def local(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    monkeypatch.setattr(config, 'ROOT', project)
    monkeypatch.setattr(config, 'DATA_DIR', project / 'data')
    path = project / 'source/resources/voice/reference.wav'
    path.parent.mkdir(parents=True)
    path.write_bytes(sample())
    application = FastAPI()
    application.include_router(services.router)
    with TestClient(application) as client:
        yield client, path, tmp_path


def test_relative_absolute_selection_and_protected_reference_route(local):
    client, path, temp = local
    relative = 'source/resources/voice/reference.wav'
    selected = client.post('/api/voice/reference/inspect', json={'path': relative})
    assert selected.status_code == 200
    info = selected.json()
    assert info['path'] == relative and info['sha256'] == hashlib.sha256(sample()).hexdigest()
    assert client.get(info['url']).content == sample()
    assert client.post('/api/voice/reference/inspect', json={'path': str(path)}).json()['id'] == info['id']
    external = temp / 'outside.WAV'
    external.write_bytes(sample())
    assert client.post('/api/voice/reference/inspect', json={'path': str(external)}).status_code == 200
    assert client.post('/api/voice/reference/inspect', json={'path': '../outside.WAV'}).status_code == 422
    assert client.post('/api/voice/reference/inspect', json={'path': 'source/missing.mp3'}).status_code == 404
    secret = temp / 'not-audio.txt'
    secret.write_text('private test text')
    assert client.post('/api/voice/reference/inspect', json={'path': str(secret)}).status_code == 422
    assert client.post('/api/voice/reference/inspect', json={'path': '\\\\server\\share\\voice.mp3'}).status_code == 422
    assert (
        client.post('/api/voice/reference/inspect', json={'path': '  \\\\server\\share\\voice.mp3'}).status_code == 422
    )


def test_upload_returns_usable_path_and_selected_file_is_cloned(local, monkeypatch):
    client, path, temp = local
    uploaded = client.post(
        '/api/voice/references/upload',
        json={'name': 'new.wav', 'format': 'wav', 'audio_base64': base64.b64encode(sample()).decode()},
    ).json()
    assert uploaded['path'].startswith('data/voice-references/')
    inspected = client.post('/api/voice/reference/inspect', json={'path': uploaded['path']}).json()
    assert inspected['sha256'] == uploaded['sha256']
    calls = []

    async def upstream(settings, secret, method, endpoint, payload, **kwargs):
        calls.append(payload)
        assert payload['audio']['voice'] == 'data:audio/wav;base64,' + base64.b64encode(sample()).decode()
        return json.dumps(
            {'choices': [{'message': {'audio': {'data': base64.b64encode(sample()).decode()}}}]}
        ).encode(), 'application/json'

    monkeypatch.setattr(voice, 'upstream', upstream)
    client.patch(
        '/api/features',
        json={'tts': {'enabled': True, 'api_key': 'clone-test-key', 'reference_path': uploaded['path']}},
    )
    assert client.post('/api/tts/synthesize', json={'text': '新文字'}).status_code == 409 and not calls
    state = client.patch('/api/features', json={'tts': {'external_reference_enabled': True}}).json()['tts']
    assert state['reference_sha256'] == uploaded['sha256'] and state['configured']
    answer = client.post('/api/tts/synthesize', json={'text': '新文字'}).json()
    assert answer['model'] == 'mimo-v2.5-tts-voiceclone' and answer['voice'] == 'reference_audio'
    assert answer['reference_sha256'] == uploaded['sha256'] and len(calls) == 1
    assert client.get(answer['audio_url']).content == sample()
    assert 'clone-test-key' not in json.dumps(answer)


def test_old_preset_model_is_rejected_without_calling_provider(local, monkeypatch):
    client, path, temp = local
    called = []

    async def upstream(*args, **kwargs):
        called.append(1)

    monkeypatch.setattr(voice, 'upstream', upstream)
    client.patch(
        '/api/features',
        json={
            'tts': {
                'enabled': True,
                'api_key': 'clone-test-key',
                'model': 'mimo-v2.5-tts',
                'voice': '冰糖',
                'reference_path': str(path),
                'external_reference_enabled': True,
            }
        },
    )
    response = client.post('/api/tts/synthesize', json={'text': '新文字'})
    assert response.status_code == 422 and '不会改用预置音色' in response.json()['detail'] and not called
