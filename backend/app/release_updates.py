"""Interactive desktop upgrades from tagged assets of this repository."""

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import config
from .constants import VERSION
from .routes.knowledge import local_installer
from .transport import ssl_context
from .updates import REPOSITORY, VERSION_PATTERN

router = APIRouter(prefix='/api/updates')
Channel = Literal['stable', 'preview']
API = 'https://api.github.com/repos/Ou-morality-uni/shunguang-companion/releases'


def select_release(rows, channel, current):
    candidates = []
    for item in rows:
        version = item.get('tag_name', '').removeprefix('v')
        if (
            item.get('tag_name') != 'v' + version
            or not re.fullmatch(VERSION_PATTERN, version)
            or item.get('draft')
            or (item.get('prerelease') and channel == 'stable')
        ):
            continue
        for asset in item.get('assets', []):
            if (
                asset.get('name') == f'shunguang-{version}-windows.zip'
                and asset.get('state') == 'uploaded'
                and re.fullmatch(r'sha256:[0-9a-f]{64}', asset.get('digest') or '')
                and 0 < asset.get('size', 0) <= 2_000_000_000
            ):
                candidates.append((tuple(map(int, version.split('.'))), version, item, asset))
                break
    if not candidates:
        raise HTTPException(404, '此渠道暂时没有已构建的 Windows 更新包。')
    number, version, item, asset = max(candidates, key=lambda entry: entry[0])
    local = tuple(map(int, current.split('.')))
    return dict(
        current_version=current,
        latest_version=version,
        status='available' if number > local else 'current' if number == local else 'ahead',
        published_at=item['published_at'][:10],
        summary=(item.get('body') or '见版本说明。')[:2000],
        release_notes_url=f'{REPOSITORY}/releases/tag/v{version}',
        checked_at=datetime.now(timezone.utc),
        cached=False,
        digest=asset['digest'][7:],
        size=asset['size'],
    )


async def discover(channel):
    try:
        async with asyncio.timeout(20), httpx.AsyncClient(verify=ssl_context(), timeout=10) as client:
            rows = []
            for page in range(1, 11):
                response = await client.get(API, params={'per_page': 100, 'page': page})
                response.raise_for_status()
                batch = response.json()
                if not isinstance(batch, list):
                    raise ValueError()
                rows.extend(batch)
                if len(batch) < 100:
                    break
            return select_release(rows, channel, VERSION)
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
        raise HTTPException(502, '无法读取 GitHub Release，请稍后重试或检查网络。') from None


def supported(request):
    return (
        local_installer(request)
        and os.environ.get('SHUNGUANG_UPDATE_SUPERVISED') == '1'
        and (config.ROOT / '.shunguang-update/baseline.json').is_file()
    )


@router.post('/releases')
async def releases(request: Request, channel: Channel = 'stable'):
    result = await discover(channel)
    return {key: value for key, value in result.items() if key not in ('digest', 'size')} | {
        'can_install': supported(request)
    }


class InstallRelease(BaseModel):
    channel: Channel
    version: str = Field(pattern=VERSION_PATTERN)


@router.post('/install', status_code=202)
async def install(request: Request, body: InstallRelease):
    origin = urlsplit(request.headers.get('origin', ''))
    if (
        not supported(request)
        or origin.scheme != request.url.scheme
        or origin.netloc != request.url.netloc
        or request.headers.get('sec-fetch-site') not in (None, 'same-origin')
        or request.headers.get('content-type', '').split(';')[0] != 'application/json'
    ):
        raise HTTPException(403, '请在运行 Start_up.bat 的电脑上打开本机网页更新。')
    release = await discover(body.channel)
    if release['status'] != 'available' or body.version != release['latest_version']:
        raise HTTPException(409, '渠道或版本已变化，请重新检查更新。')
    from scripts.desktop_update import submit_request

    try:
        job = submit_request(config.ROOT, body.version, release['digest'], release['size'])
    except FileExistsError:
        raise HTTPException(409, '已有更新正在进行。') from None
    return {'id': job}


@router.get('/progress')
def progress(request: Request):
    if not supported(request):
        raise HTTPException(403, '仅本机桌面实例可查看安装进度。')
    from scripts.desktop_update import read_json

    return read_json(config.ROOT / '.shunguang-update/status.json', {'phase': 'idle'})
