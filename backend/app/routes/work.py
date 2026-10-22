"""Local-only controls. Models cannot grant folders or approve destructive steps."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .. import runtime
from ..filework import MAX_FILE_BYTES, FileTaskRequest, WorkError, local_request, public_task
from ..schemas import DocumentUploadOut, FileTaskOut, WorkspaceOut


def service(request: Request):
    if not local_request(request):
        raise HTTPException(403, '工作台仅供运行服务的本机使用，局域网登录不会获得本机文件权限。')
    if runtime.work is None:
        raise HTTPException(503, '工作台尚未就绪。')
    return runtime.work


router = APIRouter(prefix='/api/work', dependencies=[Depends(service)])


class GrantRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=1000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approved: bool


class VisionApprovalRequest(ApprovalRequest):
    profile_id: str = Field(default='', max_length=80)
    signature: str = Field(default='', max_length=100)


def invoke(function, *args):
    try:
        return function(*args)
    except WorkError as error:
        raise HTTPException(error.status, error.message)
    except OSError:
        raise HTTPException(422, '路径不可用，请检查文件夹是否存在、文件占用及本机访问权限。')


@router.get('/workspaces', response_model=list[WorkspaceOut])
def workspaces(work=Depends(service)):
    return work.store.list_workspaces()


@router.post('/workspaces', status_code=201, response_model=WorkspaceOut)
def grant(payload: GrantRequest, work=Depends(service)):
    return invoke(work.grant, payload.path)


@router.delete('/workspaces/{workspace_id}')
def revoke(workspace_id: str, work=Depends(service)):
    invoke(work.revoke, workspace_id)
    return {'ok': True}


@router.get('/tasks', response_model=list[FileTaskOut])
def tasks(work=Depends(service)):
    return [public_task(task) for task in work.store.list_file_tasks()]


@router.post('/tasks', status_code=201, response_model=FileTaskOut)
def submit(payload: FileTaskRequest, work=Depends(service)):
    return invoke(work.submit, payload)


@router.get('/tasks/{task_id}', response_model=FileTaskOut)
def task(task_id: str, work=Depends(service)):
    return public_task(invoke(work.task, task_id))


@router.post('/tasks/{task_id}/approval', response_model=FileTaskOut)
def approve(task_id: str, payload: ApprovalRequest, work=Depends(service)):
    return invoke(work.approve, task_id, payload.approved)


@router.post('/tasks/{task_id}/cancel', response_model=FileTaskOut)
def cancel(task_id: str, work=Depends(service)):
    return invoke(work.cancel, task_id)


@router.post('/tasks/{task_id}/restore', response_model=FileTaskOut)
def restore(task_id: str, work=Depends(service)):
    return invoke(work.restore, task_id)


@router.post('/upload', response_model=DocumentUploadOut)
async def upload(request: Request, name: str = Query(min_length=1, max_length=255), work=Depends(service)):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(413, '每份上传文件最多 20 MiB。')
    return await run_in_threadpool(invoke, work.upload, name, bytes(content))


@router.get('/vision/profiles')
def vision_profiles():
    from ..document_models import profiles

    return profiles()


@router.post('/vision/probe')
async def vision_probe():
    from ..document_models import probe
    from ..llm import friendly_error

    try:
        return await probe()
    except ValueError as error:
        raise HTTPException(422, str(error))
    except Exception as error:
        raise HTTPException(502, friendly_error(error))


@router.post('/tasks/{task_id}/vision', response_model=FileTaskOut)
def vision_decision(task_id: str, payload: VisionApprovalRequest, work=Depends(service)):
    return invoke(work.approve_vision, task_id, payload.approved, payload.profile_id, payload.signature)


@router.get('/events')
def events(after: int | None = Query(default=None, ge=0), work=Depends(service)):
    return work.store.work_events(after)
