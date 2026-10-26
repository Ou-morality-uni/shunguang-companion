import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import updates
from backend.app.main import app


@pytest.fixture(autouse=True)
def fresh_update_cache(monkeypatch):
    monkeypatch.setattr(updates, 'checker', updates.UpdateChecker())


def test_manual_check_reports_a_newer_public_version(monkeypatch):
    async_client = httpx.AsyncClient

    def github(request):
        assert str(request.url) == (
            'https://raw.githubusercontent.com/Ou-morality-uni/shunguang-companion/main/update.json'
        )
        assert 'authorization' not in request.headers
        return httpx.Response(
            200,
            json={
                'version': '0.6.10',
                'published_at': '2026-10-26',
                'summary': '新的正式版本。',
                'release_notes_url': (
                    'https://github.com/Ou-morality-uni/shunguang-companion/blob/main/versions/0.6.10/README.md'
                ),
            },
        )

    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: async_client(**kwargs, transport=httpx.MockTransport(github))
    )
    response = TestClient(app).post('/api/updates/check')
    assert response.status_code == 200
    result = response.json()
    assert result['current_version'] == '0.6.3'
    assert result['latest_version'] == '0.6.10'
    assert result['status'] == 'available'
    assert result['summary'] == '新的正式版本。'
    assert result['checked_at']
    assert result['cached'] is False


@pytest.mark.parametrize('failure', ['timeout', 'missing', 'limited', 'invalid_json', 'invalid_link', 'large'])
def test_failed_checks_report_an_error_instead_of_claiming_latest(monkeypatch, failure):
    async_client = httpx.AsyncClient

    def github(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('private diagnostic', request=request)
        if failure == 'missing':
            return httpx.Response(404)
        if failure == 'limited':
            return httpx.Response(429)
        if failure == 'large':
            return httpx.Response(200, content=b' ' * 65537)
        if failure == 'invalid_link':
            return httpx.Response(
                200,
                json={
                    'version': '0.6.10',
                    'published_at': '2026-10-26',
                    'summary': 'Update',
                    'release_notes_url': 'https://example.com/untrusted',
                },
            )
        return httpx.Response(200, content=b'not json')

    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: async_client(**kwargs, transport=httpx.MockTransport(github))
    )
    response = TestClient(app, raise_server_exceptions=False).post('/api/updates/check')
    assert response.status_code in (502, 504)
    assert 'detail' in response.json()
    assert 'private diagnostic' not in response.text
    assert '已是最新' not in response.text


def test_repeated_checks_reuse_recent_success_and_keep_its_check_time(monkeypatch):
    async_client = httpx.AsyncClient
    calls = []

    def github(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                'version': '0.6.3',
                'published_at': '2026-10-26',
                'summary': '手动检查更新。',
                'release_notes_url': (
                    'https://github.com/Ou-morality-uni/shunguang-companion/blob/main/versions/0.6.3/README.md'
                ),
            },
        )

    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: async_client(**kwargs, transport=httpx.MockTransport(github))
    )
    client = TestClient(app)
    first = client.post('/api/updates/check').json()
    second = client.post('/api/updates/check').json()
    assert first['status'] == 'current'
    assert second['cached'] is True
    assert second['checked_at'] == first['checked_at']
    assert len(calls) == 1


def install_github(monkeypatch, handler):
    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, 'AsyncClient', lambda **kwargs: async_client(**kwargs, transport=httpx.MockTransport(handler))
    )


def release(version='0.6.3', **changes):
    return {
        'version': version,
        'published_at': '2026-10-26',
        'summary': '公开更新摘要',
        'release_notes_url': f'{updates.REPOSITORY}/blob/main/versions/{version}/README.md',
        **changes,
    }


@pytest.mark.parametrize(('version', 'status'), [('0.6.3', 'current'), ('0.6.2', 'ahead'), ('0.6.10', 'available')])
def test_version_comparison_is_numeric(monkeypatch, version, status):
    install_github(monkeypatch, lambda _: httpx.Response(200, json=release(version)))
    result = TestClient(app).post('/api/updates/check').json()
    assert result['status'] == status
    assert result['latest_version'] == version


@pytest.mark.parametrize(
    'changes',
    [
        {'version': 'v0.6.4'},
        {'version': '0.6.4-beta'},
        {'version': '0.6'},
        {'version': '0.06.4'},
        {'published_at': 'not-a-date'},
        {'published_at': 0},
        {'published_at': '20261026'},
        {'summary': ' '},
        {'summary': 'x' * 2001},
        {'release_notes_url': 'javascript:alert(1)'},
        {'release_notes_url': updates.REPOSITORY + '/blob/main/versions/0.6.3/README.md?redirect=evil'},
    ],
)
def test_invalid_metadata_is_rejected(monkeypatch, changes):
    install_github(monkeypatch, lambda _: httpx.Response(200, json=release(**changes)))
    response = TestClient(app).post('/api/updates/check')
    assert response.status_code == 502


def test_expired_success_does_not_hide_failure_and_retry_can_succeed(monkeypatch):
    clock = [100]
    monkeypatch.setattr(updates, 'monotonic', lambda: clock[0])
    responses = iter(
        [httpx.Response(200, json=release()), httpx.Response(503), httpx.Response(200, json=release('0.6.4'))]
    )
    install_github(monkeypatch, lambda _: next(responses))
    client = TestClient(app)
    assert client.post('/api/updates/check').json()['status'] == 'current'
    clock[0] = 161
    assert client.post('/api/updates/check').status_code == 502
    result = client.post('/api/updates/check').json()
    assert result['status'] == 'available'
    assert result['cached'] is False


def test_concurrent_manual_checks_share_one_successful_network_check(monkeypatch):
    real_client = httpx.AsyncClient
    calls = []

    async def github(request):
        calls.append(request)
        await asyncio.sleep(0.02)
        return httpx.Response(200, json=release())

    install_github(monkeypatch, github)

    async def run():
        async with real_client(transport=httpx.ASGITransport(app), base_url='http://localhost') as client:
            return await asyncio.gather(*(client.post('/api/updates/check') for _ in range(3)))

    responses = asyncio.run(run())
    assert all(response.status_code == 200 for response in responses)
    assert sorted(response.json()['cached'] for response in responses) == [False, True, True]
    assert len(calls) == 1


def test_opening_local_health_does_not_check_remote_and_lan_requires_login(monkeypatch):
    def forbidden(_):
        pytest.fail('Local health and unauthenticated requests must not contact GitHub')

    install_github(monkeypatch, forbidden)
    client = TestClient(app)
    assert client.get('/api/health').json() == {'status': 'ok', 'version': '0.6.3'}
    monkeypatch.setenv('SHUNGUANG_LAN_MODE', '1')
    assert client.post('/api/updates/check').status_code == 401
