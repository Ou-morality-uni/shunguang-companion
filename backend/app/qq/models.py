from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..model_choices import ModelChoice


class Connection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    url: str = Field(default='ws://127.0.0.1:3001', max_length=250)
    token: str = Field(default='', max_length=512)
    bot_id: str = Field(default='', pattern=r'^\d{5,20}$|^$')
    retention_days: int = Field(default=30, ge=1, le=3650)
    model_choice: ModelChoice | None = None

    @field_validator('url')
    @classmethod
    def local_ws(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != 'ws'
            or parsed.hostname not in ('127.0.0.1', '::1')
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.port
        ):
            raise ValueError('只允许本机固定端口的 ws 地址；Token 不能放在 URL 中')
        return value

    @field_validator('token')
    @classmethod
    def header_token(cls, value):
        if any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ValueError('Token 只允许可见 ASCII 字符')
        return value


class Policy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    collect: bool = False
    chat: Literal['off', 'mention', 'natural'] = 'off'
    knowledge: bool = True
    images: bool = False
    stickers: bool = True
    vision_profile: str = Field(default='', max_length=64)
    vision_signature: str = Field(default='', max_length=64)
    allow_group_send: bool = False
    schedule: Literal['off', 'daily', 'interval'] = 'off'
    daily_time: str = Field(default='22:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    interval_hours: int = Field(default=6, ge=1, le=168)
    window: Literal['incremental', 'fixed'] = 'incremental'
    window_start: str = Field(default='00:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    window_end: str = Field(default='23:59', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    delivery: Literal['panel', 'owner', 'group'] = 'panel'

    @model_validator(mode='after')
    def coherent(self):
        if (self.chat != 'off' or self.schedule != 'off') and not self.collect:
            raise ValueError('聊天或定时总结需要先开启采集')
        if self.delivery == 'group' and not self.allow_group_send:
            raise ValueError('先单独允许摘要发回原群')
        return self


class SummaryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    delivery: Literal['panel', 'owner', 'group'] = 'panel'

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start or self.end - self.start > 32 * 86400:
            raise ValueError('请选择不超过 32 天的有效时间段')
        return self
