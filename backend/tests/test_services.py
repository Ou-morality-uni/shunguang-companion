"""Mocked fault/contract tests; these are not claims of upstream availability."""

import asyncio
import base64
import io
import json
import wave
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app import config, feature_config, reminders, services, tools, voice


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    application = FastAPI()
    application.include_router(services.router)

    @application.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        return JSONResponse(status_code=422, content={'detail': '输入格式不正确。'})

    with TestClient(application) as test_client:
        yield test_client


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(b'\x00\x00' * 2400)
    return buffer.getvalue()


def fake_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )


async def allow_origin(*args):
    pass


def test_tts_connect_failure_only_one_same_origin_fallback(monkeypatch):
    original = httpx.AsyncClient
    routes, requests, verification = [], [], []

    def factory(**kwargs):
        routes.append(kwargs['trust_env'])
        verification.append(kwargs['verify'])

        def handler(request):
            requests.append(str(request.url))
            if kwargs['trust_env']:
                raise httpx.ConnectError('test-only connection failed', request=request)
            return httpx.Response(200, json={'data': []})

        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, 'AsyncClient', factory)
    result = asyncio.run(
        voice.upstream(feature_config.TTSConfig(), 'test-only-secret', 'POST', '/chat/completions', {'model': 'test'})
    )
    assert json.loads(result[0]) == {'data': []}
    assert routes == [True, False] and len(set(requests)) == 1
    assert all(item is not False for item in verification)


def test_tts_response_timeout_never_replays_post(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ReadTimeout('test-only response timeout', request=request)

    fake_http(monkeypatch, handler)
    with pytest.raises(voice.VoiceError):
        asyncio.run(
            voice.upstream(
                feature_config.TTSConfig(), 'test-only-secret', 'POST', '/chat/completions', {'model': 'test'}
            )
        )
    assert len(attempts) == 1


def test_empty_initial_services_and_secret_keep_replace_remove(client):
    state = client.get('/api/features').json()
    assert state['tts']['enabled'] is False and not state['tts']['has_api_key']
    assert state['reminders']['enabled'] is False
    assert state['tools']['search_provider'] == 'public'
    response = client.patch('/api/features', json={'tts': {'api_key': 'feature-test-secret'}})
    assert response.status_code == 200 and response.json()['tts']['has_api_key']
    assert 'feature-test-secret' not in response.text
    record = (config.DATA_DIR / 'features.json').read_text(encoding='utf-8')
    assert 'feature-test-secret' not in record and 'api_key_encrypted' in record
    assert client.patch('/api/features', json={'tts': {'api_key': '', 'voice': '茉莉'}}).status_code == 200
    assert feature_config.load().tts.api_key.get_secret_value() == 'feature-test-secret'
    assert client.patch('/api/features', json={'tts': {'api_key': 'replacement'}}).status_code == 200
    assert feature_config.load().tts.api_key.get_secret_value() == 'replacement'
    assert not client.patch('/api/features', json={'tts': {'clear_api_key': True}}).json()['tts']['has_api_key']
    assert not feature_config.load().tts.api_key.get_secret_value()


def test_key_does_not_follow_provider_or_origin_change(client):
    client.patch('/api/features', json={'tts': {'api_key': 'private-old-key'}})
    changed = client.patch(
        '/api/features', json={'tts': {'provider': 'openai', 'base_url': 'https://api.openai.com/v1', 'api_key': ''}}
    )
    assert changed.status_code == 200 and changed.json()['tts']['has_api_key'] is False
    assert not feature_config.load().tts.api_key.get_secret_value()


def test_invalid_config_is_sanitized_atomic(client, monkeypatch):
    client.patch('/api/features', json={'tools': {'api_key': 'previous-secret'}})
    previous = (config.DATA_DIR / 'features.json').read_text()
    response = client.patch(
        '/api/features',
        json={'tts': {'base_url': 'https://username:dangerous-key@example.com', 'api_key': 'do-not-expose'}},
    )
    assert response.status_code == 422
    assert 'dangerous-key' not in response.text and 'do-not-expose' not in response.text
    assert (config.DATA_DIR / 'features.json').read_text() == previous
    monkeypatch.setattr(
        feature_config, 'encrypt_secret', lambda _: (_ for _ in ()).throw(RuntimeError('private secret failure'))
    )
    response = client.patch('/api/features', json={'tools': {'api_key': 'new'}})
    assert response.status_code == 503 and 'private secret failure' not in response.text
    assert (config.DATA_DIR / 'features.json').read_text() == previous


def test_weather_missing_ambiguous_and_success(client, monkeypatch):
    assert client.post('/api/tools/run', json={'name': 'weather', 'args': {}}).json()['needs_clarification']
    calls = []

    def upstream(request):
        calls.append(request)
        if 'geocoding' in request.url.host:
            if request.url.params['name'] == 'Springfield':
                return httpx.Response(
                    200,
                    json={
                        'results': [
                            {'name': 'Springfield', 'admin1': 'A', 'country': '美国'},
                            {'name': 'Springfield', 'admin1': 'B', 'country': '美国'},
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    'results': [
                        {
                            'name': '上海',
                            'latitude': 31.23,
                            'longitude': 121.47,
                            'country_code': 'CN',
                            'country': '中国',
                            'admin1': '上海',
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                'current': {'time': '2026-10-12T12:00', 'temperature_2m': 24, 'weather_code': 2},
                'current_units': {'temperature_2m': '°C'},
                'timezone': 'Asia/Shanghai',
            },
        )

    fake_http(monkeypatch, upstream)
    result = client.post('/api/tools/run', json={'name': 'weather', 'args': {'city': 'Springfield'}}).json()
    assert result['needs_clarification'] and len(result['candidates']) == 2
    result = client.post('/api/tools/run', json={'name': 'weather', 'args': {'city': '上海', 'country': 'CN'}}).json()
    assert result['ok'] and result['current']['temperature_2m'] == 24
    assert result['sources'][0]['url'].startswith('https://api.open-meteo.com/')
    assert len(calls) == 3
    assert (
        client.post(
            '/api/tools/run', json={'name': 'weather', 'args': {'city': '上海', 'url': 'http://localhost'}}
        ).json()['code']
        == 'invalid_arguments'
    )


def test_tool_retry_budget_timeout_and_disabled(client, monkeypatch):
    count = []

    def timeout(request):
        count.append(1)
        raise httpx.ReadTimeout('secret network body', request=request)

    fake_http(monkeypatch, timeout)
    response = client.post('/api/tools/run', json={'name': 'weather', 'args': {'city': '北京'}})
    assert response.json()['code'] == 'timeout' and len(count) == 2
    assert 'secret network body' not in response.text
    client.patch('/api/features', json={'tools': {'weather_enabled': False}})
    assert (
        client.post('/api/tools/run', json={'name': 'weather', 'args': {'city': '北京'}}).json()['code'] == 'disabled'
    )


def test_client_tool_name_cannot_enable_search_or_duplicate_paid_post(client, monkeypatch):
    calls = []

    def upstream(request):
        calls.append(request)
        raise httpx.ReadTimeout('private service detail', request=request)

    fake_http(monkeypatch, upstream)
    client.patch(
        '/api/features',
        json={'tools': {'search_enabled': False, 'search_provider': 'tavily', 'api_key': 'private-tavily-test-key'}},
    )
    for name in ['web_search', 'mimo_search', 'https://api.tavily.com/search']:
        result = client.post('/api/tools/run', json={'name': name, 'args': {'query': 'Python'}}).json()
        assert result['ok'] is False and result['code'] == 'disabled' and not result.get('sources')
    assert calls == []
    client.patch('/api/features', json={'tools': {'search_enabled': True}})
    injected = client.post(
        '/api/tools/run',
        json={'name': 'web_search', 'args': {'query': 'Python', 'provider': 'mimo', 'search_enabled': True}},
    ).json()
    assert injected['code'] == 'invalid_arguments' and not calls
    # A failed paid search POST is not retried, and does not call another provider.
    result = client.post('/api/tools/run', json={'name': 'web_search', 'args': {'query': 'Python'}}).json()
    assert result['ok'] is False and result['code'] == 'timeout' and len(calls) == 1
    assert calls[0].url.host == 'api.tavily.com'


def test_search_real_contract_coverage_and_tavily_sources(client, monkeypatch):
    def upstream(request):
        if request.url.host.endswith('wikipedia.org'):
            return httpx.Response(
                200,
                json={
                    'query': {
                        'search': [{'title': 'FastAPI', 'snippet': '<span>Python</span> framework', 'pageid': 123}]
                    }
                },
            )
        assert request.headers['Authorization'] == 'Bearer search-test-key'
        assert 'search-test-key' not in str(request.url)
        assert json.loads(request.content)['max_results'] == 2
        return httpx.Response(
            200,
            json={
                'results': [
                    {
                        'title': 'FastAPI Official',
                        'url': 'https://example.org/page',
                        'content': 'FastAPI source content',
                    },
                    {'title': 'private', 'url': 'http://127.0.0.1/internal', 'content': 'discard'},
                ]
            },
        )

    fake_http(monkeypatch, upstream)
    client.patch('/api/features', json={'tools': {'search_provider': 'wikipedia'}})
    response = client.post('/api/tools/run', json={'name': 'web_search', 'args': {'query': 'FastAPI'}})
    assert response.json()['provider'] == 'Wikipedia' and '百科' in response.json()['notice']
    assert response.json()['sources'][0]['snippet'] == 'Python framework'
    client.patch('/api/features', json={'tools': {'search_provider': 'tavily'}})
    assert (
        client.post('/api/tools/run', json={'name': 'web_search', 'args': {'query': 'x'}}).json()['code']
        == 'missing_config'
    )
    client.patch('/api/features', json={'tools': {'api_key': 'search-test-key'}})
    response = client.post('/api/tools/run', json={'name': 'web_search', 'args': {'query': 'FastAPI', 'limit': 2}})
    assert response.json()['provider'] == 'Tavily' and len(response.json()['sources']) == 1
    assert 'search-test-key' not in response.text


def test_bing_rss_sources_and_unrelated_results(client, monkeypatch):
    client.patch('/api/features', json={'tools': {'search_provider': 'bing'}})

    def upstream(request):
        if request.url.params['q'] == 'Python programming language':
            return httpx.Response(
                200,
                text='<rss><channel><item><title>Welcome to Python</title><link>https://www.python.org/</link><description>Python programming language official website</description></item></channel></rss>',
            )
        return httpx.Response(
            200,
            text='<rss><channel><item><title>Unrelated design software</title><link>https://example.org/</link><description>No requested topic</description></item></channel></rss>',
        )

    fake_http(monkeypatch, upstream)
    result = client.post(
        '/api/tools/run', json={'name': 'web_search', 'args': {'query': 'Python programming language'}}
    ).json()
    assert result['ok'] and result['sources'][0]['url'] == 'https://www.python.org/'
    result = client.post(
        '/api/tools/run', json={'name': 'web_search', 'args': {'query': 'FastAPI documentation'}}
    ).json()
    assert result['code'] == 'low_relevance' and not result['sources']
    result = client.post('/api/tools/run', json={'name': 'web_search', 'args': {'query': '北京 故宫 官网'}}).json()
    assert result['code'] == 'low_relevance' and not result['sources']


def test_public_search_chinese_html_actual_source_contract_without_key(client, monkeypatch):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.method == 'POST' and request.url == 'https://html.duckduckgo.com/html/'
        assert 'Authorization' not in request.headers and 'api-key' not in request.headers
        return httpx.Response(
            200,
            text="""<html><div class="result__body"><h2><a class="result__a" href="https://www.shanghaimuseum.net/mu/frontend/pg/service/visit-east">上海博物馆</a></h2><a class="result__snippet">上海博物馆（东馆）地址：上海市浦东新区世纪大道1952号。</a></div><div class="result__body"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.shanghaimuseum.net%2F">上海博物馆官网</a><a class="result__snippet">上海博物馆官方网站</a></div><div class="result__body"><a class="result__a" href="http://127.0.0.1/secret">private</a></div></html>""",
        )

    fake_http(monkeypatch, upstream)
    # A saved key for another optional service must not enter a public request.
    client.patch('/api/features', json={'tools': {'api_key': 'unused-private-test-key'}})
    response = client.post(
        '/api/tools/run', json={'name': 'web_search', 'args': {'query': '上海博物馆东馆官网地址', 'limit': 4}}
    )
    result = response.json()
    assert result['ok'] and result['provider'] == 'DuckDuckGo HTML'
    assert result['sources'][0]['url'].endswith('/visit-east') and '1952' in result['sources'][0]['snippet']
    assert len(result['sources']) == 2 and len(calls) == 1
    assert len(result['attempts']) == 1 and result['public_best_effort']
    assert 'unused-private-test-key' not in response.text


def test_public_search_only_two_engines_and_no_validation_bypass(client, monkeypatch):
    calls = []

    def upstream(request):
        calls.append(request)
        if request.url.host == 'html.duckduckgo.com':
            return httpx.Response(202, text='<html><form id="captcha-form" action="/anomaly.js">verify</form></html>')
        return httpx.Response(429, text='private upstream failure details')

    fake_http(monkeypatch, upstream)
    response = client.post('/api/tools/run', json={'name': 'web_search', 'args': {'query': '绝区零 官方'}})
    result = response.json()
    assert result['ok'] is False and result['code'] == 'search_unavailable'
    assert not result['sources'] and len(calls) == 2
    assert [str(x.url).split('?')[0] for x in calls] == [
        'https://html.duckduckgo.com/html/',
        'https://www.bing.com/search',
    ]
    assert [x['code'] for x in result['attempts']] == ['blocked', 'blocked']
    assert 'private upstream failure details' not in response.text


def test_public_search_200_captcha_stops_main_and_fixed_origin_blocks_ssrf(client, monkeypatch):
    calls = []

    def upstream(request):
        calls.append(request)
        if request.url.host == 'html.duckduckgo.com':
            return httpx.Response(200, text='<form id="captcha-form" action="/anomaly.js">verify</form>')
        return httpx.Response(
            200,
            text='<rss><channel><item><title>Python programming language</title><link>https://www.python.org/</link><description>Python language</description></item></channel></rss>',
        )

    fake_http(monkeypatch, upstream)
    result = client.post(
        '/api/tools/run', json={'name': 'web_search', 'args': {'query': 'Python programming language'}}
    ).json()
    assert result['ok'] and result['provider'] == 'Bing RSS' and len(calls) == 2
    assert result['attempts'][0]['code'] == 'blocked'
    with pytest.raises(tools.ToolServiceError):
        asyncio.run(tools.search_content('GET', 'https://127.0.0.1/private', 5))
    assert len(calls) == 2


def test_reused_tts_key_survives_chat_provider_switch(client):
    config.save_config(
        config.ModelConfig(
            llm_base_url='https://api.xiaomimimo.com/v1', llm_model='mimo-v2.5-pro', llm_api_key='saved-mimo-test-key'
        )
    )
    config.save_config(
        config.ModelConfig(
            llm_base_url='https://api.deepseek.com', llm_model='deepseek-chat', llm_api_key='saved-deepseek-test-key'
        )
    )
    result = client.patch('/api/features', json={'tts': {'use_model_key': True}})
    assert result.status_code == 200 and result.json()['tts']['has_api_key']
    assert feature_config.tts_secret(feature_config.load().tts) == 'saved-mimo-test-key'
    assert 'saved-mimo-test-key' not in result.text


def test_mimo_discovery_and_true_audio_contract(client, monkeypatch):
    monkeypatch.setattr(voice, 'validate_origin', allow_origin)
    requests = []

    def upstream(request):
        requests.append(request)
        assert request.headers['api-key'] == 'tts-test-secret'
        if request.url.path.endswith('/models'):
            return httpx.Response(
                200,
                json={'data': [{'id': 'mimo-v2.5-tts-voiceclone'}, {'id': 'mimo-v2.5-tts'}, {'id': 'mimo-v2.5-pro'}]},
            )
        payload = json.loads(request.content)
        assert payload['messages'][-1] == {'role': 'assistant', 'content': '你好'}
        assert payload['model'] == 'mimo-v2.5-tts-voiceclone'
        assert payload['audio'] == {
            'format': 'wav',
            'voice': 'data:audio/wav;base64,' + base64.b64encode(wav_bytes()).decode('ascii'),
        }
        return httpx.Response(
            200, json={'choices': [{'message': {'audio': {'data': base64.b64encode(wav_bytes()).decode('ascii')}}}]}
        )

    fake_http(monkeypatch, upstream)
    reference = config.ROOT / 'reference.wav'
    reference.write_bytes(wav_bytes())
    uploaded = {'path': str(reference)}
    client.patch(
        '/api/features',
        json={
            'tts': {
                'enabled': True,
                'api_key': 'tts-test-secret',
                'reference_path': uploaded['path'],
                'external_reference_enabled': True,
            }
        },
    )
    discovery = client.post(
        '/api/tts/discover', json={'provider': 'mimo', 'base_url': 'https://api.xiaomimimo.com/v1'}
    ).json()
    assert discovery['models'] == [{'id': 'mimo-v2.5-tts-voiceclone'}]
    assert discovery['voices'] == []
    assert discovery['voice_discovery'] == 'local_reference_audio'
    response = client.post('/api/tts/synthesize', json={'text': '你好'})
    result = response.json()
    assert result['kind'] == 'synthesized' and result['duration'] == 0.1
    assert client.get(result['audio_url']).content == wav_bytes()
    assert 'tts-test-secret' not in response.text
    assert len(requests) == 2


def test_tts_failure_does_not_return_upstream_body(client, monkeypatch):
    monkeypatch.setattr(voice, 'validate_origin', allow_origin)
    fake_http(monkeypatch, lambda request: httpx.Response(401, text='super-private-upstream-key'))
    assert client.post('/api/tts/synthesize', json={'text': '你好'}).status_code == 503
    reference = config.ROOT / 'reference.wav'
    reference.write_bytes(wav_bytes())
    uploaded = {'path': str(reference)}
    client.patch(
        '/api/features',
        json={
            'tts': {
                'enabled': True,
                'api_key': 'example-secret',
                'reference_path': uploaded['path'],
                'external_reference_enabled': True,
            }
        },
    )
    response = client.post('/api/tts/synthesize', json={'text': '你好'})
    assert response.status_code == 502 and 'super-private-upstream-key' not in response.text


def test_reference_archive_disabled_without_writing_files(client):
    response = client.post(
        '/api/voice/references/upload',
        json={'name': 'sample.wav', 'format': 'wav', 'audio_base64': base64.b64encode(wav_bytes()).decode()},
    )
    assert response.status_code == 410
    assert not (config.DATA_DIR / 'voice-references').exists()


def test_origin_rejects_private_addresses_and_wrong_presets(monkeypatch):
    monkeypatch.setattr(voice.socket, 'getaddrinfo', lambda *args, **kwargs: [(2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(voice.VoiceError):
        asyncio.run(voice.validate_origin('https://metadata.example/v1', 'custom'))
    with pytest.raises(voice.VoiceError):
        asyncio.run(voice.validate_origin('https://wrong.example/v1', 'mimo'))


def test_reminder_due_restart_pause_quiet_reconnect_no_backlog(client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(reminders.time, 'time', lambda: now[0])
    client.patch(
        '/api/features',
        json={'reminders': {'enabled': True, 'interval_minutes': 1, 'quiet_start': '00:00', 'quiet_end': '00:00'}},
    )
    assert client.get('/api/reminders/poll').json()['event'] is None
    now[0] += 61
    first = client.get('/api/reminders/poll').json()['event']
    assert first and not first['test']
    assert client.get('/api/reminders/poll').json()['event'] is None
    assert reminders.read_state()['last_event_id'] == first['id']
    # Reopening/reloading the state doesn't replay a delivered reminder.
    assert feature_config.load().reminders.enabled
    now[0] += 1000
    response = client.get('/api/reminders/poll').json()
    assert response['reconnected'] and response['event'] is None
    now[0] += 61
    assert client.get('/api/reminders/poll').json()['event']['id'] != first['id']
    pause_until = datetime.fromtimestamp(now[0] + 3600, timezone.utc).isoformat()
    client.patch('/api/features', json={'reminders': {'paused_until': pause_until}})
    assert client.get('/api/reminders/poll').json()['paused']
    assert client.get('/api/reminders/poll').json()['event'] is None
    tested = client.post('/api/reminders/test').json()['event']
    assert tested['test'] and tested['id'] != first['id']
    client.patch(
        '/api/features', json={'reminders': {'paused_until': None, 'quiet_start': '00:00', 'quiet_end': '23:59'}}
    )
    assert client.get('/api/reminders/poll').json()['quiet']
    now[0] += 61
    assert client.get('/api/reminders/poll').json()['event'] is None
