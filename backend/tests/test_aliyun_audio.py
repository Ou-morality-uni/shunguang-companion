"""Current Qwen-Audio protocol and private transient uploads, without cloud charges."""

import asyncio
import base64
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import aliyun_audio, cloud_voices, config, feature_config, services, voice
from backend.app import tts_providers as tts

MODEL = 'qwen-audio-3.1-tts-flash'
PCM = b'\x01\x00' * 2400


def settings(**patch):
    return feature_config.TTSConfig(
        **{
            'provider': 'aliyun',
            'enabled': True,
            'api_key': 'unit-key',
            'model': MODEL,
            'base_url': 'https://dashscope.aliyuncs.com',
            'voice': MODEL + '-test-123',
            'external_reference_enabled': True,
            **patch,
        }
    )


def socket(monkeypatch, fail=False):
    sent = []

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, raw):
            sent.append(json.loads(raw))

        def __aiter__(self):
            return self.events()

        async def events(self):
            task = sent[0]['header']['task_id']
            if fail:
                yield json.dumps(
                    {
                        'header': {
                            'task_id': task,
                            'event': 'task-failed',
                            'error_code': 'ModelNotFound',
                            'error_message': 'private detail',
                        }
                    }
                )
                return
            yield json.dumps({'header': {'task_id': task, 'event': 'task-started'}})
            if any(x['header']['action'] == 'continue-task' for x in sent):
                yield PCM
            yield json.dumps({'header': {'task_id': task, 'event': 'task-finished'}})

    def connect(uri, **kw):
        assert uri == 'wss://dashscope.aliyuncs.com/api-ws/v1/inference'
        return Socket()

    monkeypatch.setattr(tts, 'NoRedirectConnect', connect)
    return sent


def test_current_audio_protocol_streams_pcm_and_waits_for_completion(monkeypatch):
    sent = socket(monkeypatch)
    result = asyncio.run(voice.synthesize(settings(), '你好'))
    assert result['duration'] == 0.1
    assert [x['header']['action'] for x in sent] == ['run-task', 'continue-task', 'finish-task']
    assert sent[0]['payload']['parameters']['voice'] == settings().voice
    assert len({x['header']['task_id'] for x in sent}) == 1


def test_model_check_never_sends_text(monkeypatch):
    sent = socket(monkeypatch)
    assert asyncio.run(tts.check_model(settings()))['ok']
    assert [x['header']['action'] for x in sent] == ['run-task', 'finish-task']


def test_current_model_is_available_through_browser_stream_route(monkeypatch):
    socket(monkeypatch)
    feature_config.save(feature_config.FeatureConfig(tts=settings()))
    app = FastAPI()
    app.include_router(services.router)
    with TestClient(app) as client:
        response = client.post('/api/tts/stream', json={'text': '你好'})
    assert response.status_code == 200
    assert 'event: audio' in response.text and 'event: done' in response.text
    assert 'event: error' not in response.text and 'unit-key' not in response.text


def test_task_failure_never_caches_audio_or_exposes_provider_prose(monkeypatch):
    socket(monkeypatch, fail=True)
    with pytest.raises(voice.VoiceError) as error:
        asyncio.run(voice.synthesize(settings(), '你好'))
    assert error.value.code == 'model' and 'private detail' not in error.value.message
    assert not list(config.DATA_DIR.glob('audio/*.wav'))


def test_private_oss_enrollment_and_management(monkeypatch):
    feature_config.save(feature_config.FeatureConfig(tts=settings()))
    created = []

    def handler(request):
        if request.url.path == '/api/v1/uploads':
            assert request.url.params['model'] == 'voice-enrollment'
            return httpx.Response(
                200,
                json={
                    'data': {
                        'upload_host': 'https://dashscope-file-test.oss-cn-beijing.aliyuncs.com',
                        'upload_dir': 'dashscope-instant/test',
                        'oss_access_key_id': 'temporary-only',
                        'policy': 'policy',
                        'signature': 'signature',
                        'x_oss_object_acl': 'private',
                        'x_oss_forbid_overwrite': 'true',
                    }
                },
            )
        if '.oss-' in request.url.host:
            assert 'authorization' not in request.headers
            assert b'unit-key' not in request.content and b'temporary-only' in request.content
            return httpx.Response(200)
        payload = json.loads(request.content)
        assert payload['model'] == 'voice-enrollment'
        action = payload['input']['action']
        if action == 'create_voice':
            fields = payload['input']
            assert fields['url'].startswith('oss://') and len(fields['prefix']) <= 10
            assert request.headers['X-DashScope-OssResourceResolve'] == 'enable'
            created.append({'voice_id': MODEL + '-' + fields['prefix'] + '-test', 'status': 'DEPLOYING'})
            return httpx.Response(200, json={'output': {'voice_id': created[0]['voice_id']}})
        if action == 'delete_voice':
            assert payload['input']['voice_id'] == created[0]['voice_id']
            created.clear()
            return httpx.Response(200, json={'output': {}})
        assert action == 'list_voice'
        return httpx.Response(200, json={'output': {'voice_list': created}})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))

    async def check(_):
        return {'ok': True}

    monkeypatch.setattr(tts, 'check_model', check)
    monkeypatch.setattr(
        cloud_voices,
        'uploaded_reference',
        lambda *a: ({'sha256': 'digest'}, 'data:audio/wav;base64,' + base64.b64encode(PCM).decode()),
    )
    result = asyncio.run(cloud_voices.create('声音一', 'encoded', 'wav'))
    assert result['voice'] == feature_config.load().tts.voice
    listing = asyncio.run(cloud_voices.list_voices())
    assert listing['voices'][0]['status'] == 'DEPLOYING'
    with pytest.raises(voice.VoiceError):
        asyncio.run(cloud_voices.choose(result['voice']))
    created[0]['status'] = 'OK'
    assert asyncio.run(cloud_voices.choose(result['voice']))['tts']['voice'] == result['voice']
    assert asyncio.run(cloud_voices.delete(result['voice']))['tts']['voice'] == ''
    assert not (config.DATA_DIR / 'voice-references').exists()


def test_upload_failure_does_not_leave_pending_enrollment(monkeypatch):
    feature_config.save(feature_config.FeatureConfig(tts=settings()))

    async def check(_):
        return {'ok': True}

    async def upload(*_):
        raise voice.VoiceError('failed before enrollment', stage='upload')

    monkeypatch.setattr(tts, 'check_model', check)
    monkeypatch.setattr(aliyun_audio, 'upload_reference', upload)
    monkeypatch.setattr(
        cloud_voices, 'uploaded_reference', lambda *a: ({'sha256': 'digest'}, 'data:audio/wav;base64,AQA=')
    )
    with pytest.raises(voice.VoiceError):
        asyncio.run(cloud_voices.create('test', 'encoded', 'wav'))
    assert cloud_voices.read_catalog() == []
