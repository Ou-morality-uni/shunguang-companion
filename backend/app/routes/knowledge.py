import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from ..config import (
    ROOT,
    local_knowledge_enabled,
)

router = APIRouter()


class InstallConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed: bool


def local_installer(request):
    from .. import access, service_install
    from ..file_paths import local_request

    return (
        service_install.supported()
        and not access.lan_mode()
        and local_request(request)
        and request.url.hostname in ('localhost', '127.0.0.1', '::1')
        and not any(name == 'forwarded' or name.startswith('x-forwarded-') for name in request.headers)
    )


@router.get('/api/services/install')
def service_status(request: Request):
    from .. import rag, runtime, service_install

    allowed = local_installer(request)
    ready = local_knowledge_enabled() and rag.status()['ready']
    return {
        'base_ready': True,
        'qq_status': runtime.qq.status if runtime.qq is not None else 'not_started',
        'knowledge_ready': ready,
        'can_install_knowledge': allowed,
        'knowledge_install': service_install.snapshot() if allowed else None,
    }


@router.post('/api/services/install/knowledge', status_code=202)
def install_knowledge(payload: InstallConfirmation, request: Request):
    from .. import service_install

    try:
        origin = urlsplit(request.headers.get('origin', ''))
    except ValueError:
        raise HTTPException(403, '访问来源无效。') from None
    if (
        not local_installer(request)
        or origin.scheme != request.url.scheme
        or origin.netloc != request.url.netloc
        or request.headers.get('sec-fetch-site') not in (None, 'same-origin')
        or request.headers.get('content-type', '').split(';', 1)[0].strip() != 'application/json'
    ):
        raise HTTPException(403, '只能从本机桌面网页安装知识库。')
    if not payload.confirmed:
        raise HTTPException(422, '请先确认知识库下载和磁盘占用。')
    return service_install.start()


class RagQuery(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=4, ge=1, le=10)
    allow_spoilers: bool = False


@router.get('/api/rag/status')
def rag_status():
    if not local_knowledge_enabled():
        return {
            'enabled': False,
            'ready': False,
            'available': False,
            'runtime_installed': False,
            'notice': '本地知识库尚未启用，可前往陪伴设置的服务管理按需安装。',
        }
    from .. import rag

    return rag.status()


@router.post('/api/rag/rebuild')
async def rag_rebuild():
    if not local_knowledge_enabled():
        raise HTTPException(409, '轻量模式已禁用本地知识库。')
    from .. import rag

    try:
        return await asyncio.to_thread(rag.rebuild)
    except Exception:
        raise HTTPException(503, '索引构建失败，请查看本机检索安装与模型文件状态。')


@router.post('/api/rag/search')
async def rag_search(payload: RagQuery):
    if not local_knowledge_enabled():
        raise HTTPException(409, '轻量模式已禁用本地知识库。')
    from .. import rag

    try:
        return {'sources': await asyncio.to_thread(rag.search, payload.query, payload.limit, payload.allow_spoilers)}
    except Exception:
        raise HTTPException(503, '本地检索暂未就绪，请先安装检索运行环境并构建索引。')


@router.get('/api/resources/{resource_path:path}')
def resource(resource_path: str):
    allowed = ('character/avatar.png', 'character/stickers/', 'assets/ye-shunguang/')
    if resource_path != allowed[0] and not resource_path.startswith(allowed[1:]):
        raise HTTPException(404, '资源不存在。')
    root = (ROOT / 'source/resources').resolve()
    target = (root / resource_path).resolve()
    if (
        not target.is_relative_to(root)
        or target.suffix.lower() not in ('.png', '.jpg', '.webp')
        or not target.is_file()
    ):
        raise HTTPException(404, '资源不存在。')
    return FileResponse(target)
