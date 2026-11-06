"""Single-user LAN protection. Passwords/tokens never appear in URLs or logs."""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import time
from threading import RLock
from urllib.parse import urlparse

from fastapi.responses import JSONResponse

from . import config
from .config_files import quarantine, read_object

SESSION_LOCK = RLock()
sessions = {}
attempts = {}
MAX_SESSIONS = 1024
MAX_ATTEMPT_HOSTS = 4096
COOKIE = 'shunguang_session'
HOST_LOCK = RLock()
_host_addresses = set()
_host_expires = 0.0


def lan_mode():
    return os.environ.get('SHUNGUANG_LAN_MODE', '0') == '1'


def save_password(password):
    if len(password) < 10:
        raise ValueError('局域网口令至少10个字符')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 300_000).hex()
    path = config.DATA_DIR / 'access.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'salt': salt, 'hash': digest}), encoding='utf-8')
    os.replace(tmp, path)


def check_password(password):
    path = config.DATA_DIR / 'access.json'
    if not path.exists():
        return False
    record = read_object(path)
    try:
        salt = bytes.fromhex(record.get('salt', ''))
        expected = bytes.fromhex(record.get('hash', ''))
        if len(salt) != 16 or len(expected) != 32:
            raise ValueError()
    except (ValueError, TypeError):
        quarantine(path)
        return False
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 300_000)
    return hmac.compare_digest(digest, expected)


def authenticated(request):
    if not lan_mode():
        return True
    token = request.cookies.get(COOKIE, '')
    with SESSION_LOCK:
        prune_auth()
        expiry = sessions.get(token, 0)
        return expiry > time.time()


def login(request, password):
    host = request.client.host if request.client else 'unknown'
    with SESSION_LOCK:
        prune_auth()
        if host not in attempts and len(attempts) >= MAX_ATTEMPT_HOSTS:
            return JSONResponse({'detail': '登录请求较多，请稍后重试。'}, status_code=429)
        recent = [t for t in attempts.get(host, []) if time.time() - t < 300]
        attempts[host] = recent
        if len(recent) >= 8:
            return JSONResponse({'detail': '尝试过于频繁，请五分钟后重试。'}, status_code=429)
        recent.append(time.time())
    if not check_password(password):
        return JSONResponse({'detail': '访问口令不正确，或局域网保护尚未设置。'}, status_code=401)
    token = secrets.token_urlsafe(32)
    with SESSION_LOCK:
        prune_auth()
        if len(sessions) >= MAX_SESSIONS:
            return JSONResponse({'detail': '登录会话已满，请稍后重试。'}, status_code=429)
        sessions[token] = time.time() + 12 * 3600
        attempts.pop(host, None)
    response = JSONResponse({'ok': True})
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite='strict',
        secure=request.url.scheme == 'https',
        max_age=12 * 3600,
        path='/',
    )
    return response


def prune_auth():
    now = time.time()
    for token in [key for key, expiry in sessions.items() if expiry <= now]:
        del sessions[token]
    for host, recent in list(attempts.items()):
        recent = [stamp for stamp in recent if now - stamp < 300]
        if recent:
            attempts[host] = recent
        else:
            del attempts[host]


def allowed_hosts():
    hosts = {'127.0.0.1', 'localhost', '::1'}
    global _host_addresses, _host_expires
    with HOST_LOCK:
        if time.monotonic() >= _host_expires:
            try:
                _host_addresses = {row[4][0] for row in socket.getaddrinfo(socket.gethostname(), None)}
            except OSError:
                _host_addresses = set()
            _host_expires = time.monotonic() + 60
        hosts.update(_host_addresses)
    hosts.update(x.strip() for x in os.environ.get('SHUNGUANG_ALLOWED_HOSTS', '').split(',') if x.strip())
    return hosts


async def guard(request, call_next):
    host = request.url.hostname
    is_test = host == 'testserver' and request.client and request.client.host == 'testclient'
    if (
        host not in {'localhost', '127.0.0.1', '::1'}
        and not is_test
        and host not in await asyncio.to_thread(allowed_hosts)
    ):
        return JSONResponse({'detail': '访问地址不属于本机服务。'}, status_code=403)
    if not lan_mode() and request.client:
        peer = request.client.host
        if peer != 'testclient':
            try:
                if not ipaddress.ip_address(peer).is_loopback:
                    return JSONResponse({'detail': '当前为本机模式，请使用局域网启动脚本。'}, status_code=403)
            except ValueError:
                return JSONResponse({'detail': '访问来源无效。'}, status_code=403)
    origin = request.headers.get('origin')
    if origin:
        parsed = urlparse(origin)
        same = parsed.netloc == request.url.netloc and parsed.scheme == request.url.scheme
        dev = not lan_mode() and parsed.hostname in ('127.0.0.1', 'localhost') and parsed.port == 5173
        if not (same or dev):
            return JSONResponse({'detail': '跨站访问已阻止。'}, status_code=403)
    public = request.url.path in (
        '/',
        '/api/health',
        '/api/auth/status',
        '/api/auth/login',
    ) or request.url.path.startswith('/assets/')
    if lan_mode() and not public and not authenticated(request):
        return JSONResponse({'detail': '请先输入局域网访问口令。', 'code': 'lan_auth_required'}, status_code=401)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response
