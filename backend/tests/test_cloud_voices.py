import asyncio
import base64
import io
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import cloud_voices, config, feature_config, services, tts_providers, voice


def sample():
    data = io.BytesIO()
    with wave.open(data, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b'\x01\x00' * 2400)
    return base64.b64encode(data.getvalue()).decode()


@pytest.fixture(autouse=True)
def offline_model_check(monkeypatch):
    async def check(settings):
        return {'ok': True}

    monkeypatch.setattr(tts_providers, 'check_model', check)


def configure():
    feature_config.update(
        {
            'tts': {
                'provider': 'aliyun',
                'base_url': 'https://dashscope.aliyuncs.com',
                'model': 'qwen3-tts-vc-realtime-2026-01-15',
                'api_key': 'test-key',
                'external_reference_enabled': True,
                'enabled': True,
            }
        }
    )


def test_create_auto_selects_multiple_voices_reuses_and_deletes(monkeypatch):
    configure()
    remote = []
    calls = []

    async def upstream(settings, secret, method, path, payload=None, **kwargs):
        assert secret == 'test-key'
        fields = payload['input']
        calls.append(fields['action'])
        if fields['action'] == 'create':
            assert fields['audio']['data'].startswith('data:audio/wav;base64,')
            item = {'voice': f'voice-{len(remote) + 1}', 'target_model': settings.model, 'gmt_create': 'today'}
            remote.append(item)
            return json.dumps({'output': {'voice': item['voice'], 'target_model': settings.model}}).encode(), ''
        if fields['action'] == 'delete':
            remote[:] = [x for x in remote if x['voice'] != fields['voice']]
            return b'{"output":{"voice":"deleted"}}', ''
        return json.dumps({'output': {'voice_list': remote}}).encode(), ''

    monkeypatch.setattr(voice, 'upstream', upstream)
    app = FastAPI()
    app.include_router(services.router)
    with TestClient(app) as client:
        first = client.post('/api/tts/register', json={'name': '声音一', 'format': 'wav', 'audio_base64': sample()})
        assert first.status_code == 200, first.text
        assert first.json()['features']['tts']['voice'] == 'voice-1'
        assert feature_config.load().tts.voice == 'voice-1'
        second = client.post('/api/tts/register', json={'name': '声音一', 'format': 'wav', 'audio_base64': sample()})
        assert second.json()['reused'] and calls.count('create') == 1
        remote.append({'voice': 'another', 'target_model': feature_config.load().tts.model})
        remote.append({'voice': 'wrong-model', 'target_model': 'different'})
        assert len(client.get('/api/tts/voices').json()['voices']) == 2
        assert client.post('/api/tts/voices/select', json={'voice': 'wrong-model'}).status_code == 409
        assert client.post('/api/tts/voices/select', json={'voice': 'another'}).json()['tts']['voice'] == 'another'
        assert client.post('/api/tts/voices/delete', json={'voice': 'another'}).json()['tts']['voice'] == ''
    assert not (config.DATA_DIR / 'voice-references').exists()
    assert 'test-key' not in (config.DATA_DIR / 'cloud-voices.json').read_text(encoding='utf-8')


def test_unknown_creation_is_not_automatically_replayed(monkeypatch):
    configure()
    attempts = []

    async def fail(*args, **kwargs):
        attempts.append(True)
        raise voice.VoiceError('response timeout')

    monkeypatch.setattr(voice, 'upstream', fail)
    for _ in range(2):
        with pytest.raises(voice.VoiceError):
            asyncio.run(cloud_voices.create('test', sample(), 'wav'))
    assert len(attempts) == 1


def test_definitive_rejection_does_not_permanently_block_manual_retry(monkeypatch):
    configure()
    attempts = []

    async def denied(*args, **kwargs):
        attempts.append(True)
        raise voice.VoiceError('model rejected', 400, code='model', retry_safe=True)

    monkeypatch.setattr(voice, 'upstream', denied)
    for _ in range(2):
        with pytest.raises(voice.VoiceError):
            asyncio.run(cloud_voices.create('test', sample(), 'wav'))
    assert len(attempts) == 2
    assert cloud_voices.read_catalog()[0]['state'] == 'failed'


def test_retired_provider_config_is_disabled_without_reusing_its_key():
    feature_config.save(
        feature_config.FeatureConfig(
            tts=feature_config.TTSConfig(provider='volcengine', enabled=True, api_key='old-volc-secret')
        )
    )
    current = feature_config.load().tts
    assert current.provider == 'mimo' and not current.enabled
    assert feature_config.tts_secret(current) == ''


def test_model_preflight_failure_never_creates_or_journals(monkeypatch):
    configure()
    calls = []

    async def failed_check(settings):
        raise voice.VoiceError('model unavailable', code='model_unavailable')

    async def upstream(*args, **kwargs):
        calls.append(True)

    monkeypatch.setattr(tts_providers, 'check_model', failed_check)
    monkeypatch.setattr(voice, 'upstream', upstream)
    with pytest.raises(voice.VoiceError):
        asyncio.run(cloud_voices.create('sample', sample(), 'wav'))
    assert calls == []
    assert not (config.DATA_DIR / 'cloud-voices.json').exists()


def test_vendor_profiles_keep_distinct_encrypted_keys_across_switches():
    feature_config.update({'tts': {'api_key': 'mimo-only'}})
    configure()
    profile = feature_config.saved_tts_profile('mimo', 'https://api.xiaomimimo.com/v1')
    assert profile.api_key.get_secret_value() == 'mimo-only'
    feature_config.update({'tts': {'provider': 'mimo', 'base_url': 'https://api.xiaomimimo.com/v1', 'api_key': ''}})
    assert feature_config.load().tts.api_key.get_secret_value() == 'mimo-only'
    feature_config.update({'tts': {'provider': 'aliyun', 'base_url': 'https://dashscope.aliyuncs.com', 'api_key': ''}})
    assert feature_config.load().tts.api_key.get_secret_value() == 'test-key'
    saved = (config.DATA_DIR / 'tts-profiles.json').read_text(encoding='utf-8')
    assert 'mimo-only' not in saved and 'test-key' not in saved
