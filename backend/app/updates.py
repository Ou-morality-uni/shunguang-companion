"""Read public version metadata only; never install or run an update."""

import asyncio
import re
from datetime import date, datetime, timezone
from time import monotonic
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .constants import VERSION
from .transport import ssl_context

REPOSITORY = 'https://github.com/Ou-morality-uni/shunguang-companion'
UPDATE_URL = 'https://raw.githubusercontent.com/Ou-morality-uni/shunguang-companion/main/update.json'
VERSION_PATTERN = r'^(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})$'


class ReleaseInfo(BaseModel):
    version: str = Field(pattern=VERSION_PATTERN)
    published_at: date
    summary: str = Field(min_length=1, max_length=2000)
    release_notes_url: str = Field(max_length=300)

    @field_validator('published_at', mode='before')
    @classmethod
    def iso_date(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            raise ValueError('Expected an ISO date')
        return value

    @model_validator(mode='after')
    def validate_release(self):
        expected = f'{REPOSITORY}/blob/main/versions/{self.version}/README.md'
        if self.release_notes_url != expected or not self.summary.strip():
            raise ValueError('Invalid release information')
        return self


class UpdateCheckOut(BaseModel):
    current_version: str
    latest_version: str
    status: Literal['available', 'current', 'ahead']
    published_at: date
    summary: str
    release_notes_url: str
    checked_at: datetime
    cached: bool = False


async def fetch_release():
    try:
        async with asyncio.timeout(10):
            async with httpx.AsyncClient(timeout=10, verify=ssl_context(), follow_redirects=False) as client:
                async with client.stream('GET', UPDATE_URL) as response:
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 65536:
                            raise HTTPException(502, '更新信息过大，无法检查，请稍后重试。')
                    release = ReleaseInfo.model_validate_json(bytes(content))
    except (TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, '检查更新超时，请检查网络后重试。') from None
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            detail = '更新信息尚未发布，暂时无法检查，请稍后重试。'
        elif error.response.status_code in (403, 429):
            detail = '更新服务暂时拒绝请求或受到限流，请稍后重试。'
        else:
            detail = '更新服务暂不可用，请稍后重试。'
        raise HTTPException(502, detail) from None
    except httpx.RequestError:
        raise HTTPException(502, '无法连接更新服务，请检查网络后重试。') from None
    except ValidationError:
        raise HTTPException(502, '更新信息格式不正确，暂时无法检查，请稍后重试。') from None
    local = tuple(map(int, VERSION.split('.')))
    remote = tuple(map(int, release.version.split('.')))
    return UpdateCheckOut(
        current_version=VERSION,
        latest_version=release.version,
        status='available' if remote > local else 'ahead' if local > remote else 'current',
        published_at=release.published_at,
        summary=release.summary,
        release_notes_url=release.release_notes_url,
        checked_at=datetime.now(timezone.utc),
    )


class UpdateChecker:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.result = None
        self.expires_at = 0

    async def check(self):
        async with self.lock:
            if self.result is not None and monotonic() < self.expires_at:
                return self.result.model_copy(update={'cached': True})
            # Expired results must not mask a failed fresh check.
            self.result = None
            result = await fetch_release()
            self.result = result
            self.expires_at = monotonic() + 60
            return result


checker = UpdateChecker()


async def check():
    return await checker.check()
