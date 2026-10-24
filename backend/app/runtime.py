"""Single-worker runtime shared by routes. Persistent state belongs to Store."""

import asyncio

from fastapi import HTTPException

from . import config
from .filework import FileWork
from .store import Store

store = Store(config.DATA_DIR / 'companion.sqlite3')
busy: set[str] = set()
stops: dict[str, asyncio.Event] = {}
finished: dict[str, asyncio.Future[bool]] = {}
mutation_lock = asyncio.Lock()
work: FileWork | None = None
weather_care = None
memory_jobs = None


def require_conversation(conversation_id):
    if not store.get_conversation(conversation_id):
        raise HTTPException(404, '对话不存在')


def require_config():
    value = config.load_config()
    if not config.public_config(value)['configured']:
        raise HTTPException(503, '请在设置界面填写模型名称和 API 密钥，并保存配置。')
    return value
