"""Local-only controls. Models cannot grant folders or approve destructive steps."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .. import runtime
from ..filework import FileTaskRequest, WorkError, local_request, public_task
from ..schemas import FileTaskOut, WorkspaceOut


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
