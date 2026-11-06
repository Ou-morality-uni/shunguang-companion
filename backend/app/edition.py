"""Optional QQ integration shared by desktop and server distributions."""

from fastapi import HTTPException

from .routes.qq import router

routers = (router,)


def dependency_status():
    from . import runtime

    return {'qq': runtime.qq.status if runtime.qq is not None else 'not_started'}


async def start():
    from . import config, runtime
    from .qq.repository import QQRepository
    from .qq.service import QQService

    runtime.qq = QQService(QQRepository(config.DATA_DIR / 'qq'))
    await runtime.qq.start()


async def close():
    from . import runtime

    if runtime.qq is not None:
        await runtime.qq.close()
        runtime.qq = None


def conversation_ids():
    from . import runtime

    return {item['conversation'] for item in runtime.qq.repo.scopes()} if runtime.qq is not None else set()


def require_web_conversation(conversation_id):
    if conversation_id in conversation_ids():
        raise HTTPException(409, '这是 QQ 对话，请到 QQ 接入中查看和管理。')
