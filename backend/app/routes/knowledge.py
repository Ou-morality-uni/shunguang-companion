import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import (
    ROOT,
)

router = APIRouter()


class RagQuery(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=4, ge=1, le=10)
    allow_spoilers: bool = False


@router.get('/api/rag/status')
def rag_status():
    from .. import rag

    return rag.status()


@router.post('/api/rag/rebuild')
async def rag_rebuild():
    from .. import rag

    try:
        return await asyncio.to_thread(rag.rebuild)
    except Exception:
        raise HTTPException(503, '索引构建失败，请查看本机检索安装与模型文件状态。')


@router.post('/api/rag/search')
async def rag_search(payload: RagQuery):
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
