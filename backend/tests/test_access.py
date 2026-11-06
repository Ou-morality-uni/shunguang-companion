"""Exercise the real protection middleware with synthetic clients."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import access
from backend.app.access import allowed_hosts as real_allowed_hosts
from backend.app.routes import settings


@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setenv('SHUNGUANG_LAN_MODE', '1')
    monkeypatch.setattr(access, 'sessions', {})
    monkeypatch.setattr(access, 'attempts', {})
    access.save_password('synthetic-password')
    app = FastAPI()
    app.middleware('http')(access.guard)
    app.include_router(settings.router)
    with TestClient(app, base_url='https://localhost', client=('192.0.2.8', 4000)) as client:
        yield client


def test_untrusted_host_and_cross_site_origin_are_rejected(protected):
    assert protected.get('/api/health', headers={'Host': 'attacker.example'}).status_code == 403
    assert (
        protected.post(
            '/api/auth/login', headers={'Origin': 'https://attacker.example'}, json={'password': 'synthetic-password'}
        ).status_code
        == 403
    )


def test_lan_requires_login_and_sets_secure_cookie(protected):
    assert protected.get('/api/settings').status_code == 401
    response = protected.post('/api/auth/login', json={'password': 'synthetic-password'})
    assert response.status_code == 200
    cookie = response.headers['set-cookie'].lower()
    assert all(flag in cookie for flag in ['httponly', 'secure', 'samesite=strict'])
    assert protected.get('/api/settings').status_code == 200


def test_eight_failed_attempts_lock_out_even_correct_password(protected):
    for _ in range(8):
        assert protected.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
    assert protected.post('/api/auth/login', json={'password': 'synthetic-password'}).status_code == 429


def test_session_capacity_rejects_new_login_without_revoking_existing_session(protected, monkeypatch):
    monkeypatch.setattr(access, 'MAX_SESSIONS', 1, raising=False)
    assert protected.post('/api/auth/login', json={'password': 'synthetic-password'}).status_code == 200
    assert protected.post('/api/auth/login', json={'password': 'synthetic-password'}).status_code == 429
    assert protected.get('/api/settings').status_code == 200


def test_localhost_requests_do_not_wait_for_slow_host_refresh(monkeypatch):
    import asyncio
    import threading

    import httpx

    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(access, 'allowed_hosts', real_allowed_hosts)
    monkeypatch.setattr(access, '_host_expires', 0.0)
    monkeypatch.setattr(access, '_host_addresses', set())

    def lookup(*args):
        started.set()
        release.wait(2)
        return [(None, None, None, None, ('192.0.2.99', 0))]

    monkeypatch.setattr(access.socket, 'getaddrinfo', lookup)
    app = FastAPI()
    app.middleware('http')(access.guard)

    @app.get('/probe')
    def probe():
        return {'ok': True}

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            slow = asyncio.create_task(client.get('http://192.0.2.99/probe'))
            await asyncio.to_thread(started.wait, 1)
            try:
                response = await asyncio.wait_for(client.get('http://localhost/probe'), 0.2)
                assert response.status_code == 200
            finally:
                release.set()
                await slow

    asyncio.run(run())
