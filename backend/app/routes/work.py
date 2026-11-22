"""Local attachment reading and historical downloads."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .. import runtime
from ..filework import MAX_FILE_BYTES, WorkError, local_request, public_task
from ..schemas import DocumentUploadOut, FileTaskOut


def service(request: Request):
    if not local_request(request):
        raise HTTPException(403, '附件和历史成果仅供运行服务的本机使用。')
    if runtime.work is None:
        raise HTTPException(503, '附件服务尚未就绪。')
    return runtime.work


router = APIRouter(prefix='/api/work', dependencies=[Depends(service)])


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approved: bool


class RetrySummaryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    extend_timeout: bool = False


class VisionApprovalRequest(ApprovalRequest):
    profile_id: str = Field(default='', max_length=80)
    signature: str = Field(default='', max_length=100)


def invoke(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except WorkError as error:
        raise HTTPException(error.status, error.message)
    except OSError:
        raise HTTPException(422, '路径不可用，请检查文件夹是否存在、文件占用及本机访问权限。')


@router.get('/tasks', response_model=list[FileTaskOut])
def tasks(
    conversation_id: str | None = Query(default=None, max_length=80),
    compact: bool = False,
    artifacts_only: bool = False,
    offset: int = Query(default=0, ge=0, le=1000000),
    work=Depends(service),
):
    records = [
        public_task(task)
        for task in work.store.list_file_tasks(
            conversation_id=conversation_id, artifacts_only=artifacts_only, offset=offset
        )
    ]
    if compact:
        for task in records:
            for step in task['steps']:
                result = step.get('result')
                if result and len(result.get('blocks', [])) > 30:
                    step['result'] = {**result, 'blocks': result['blocks'][:30], 'preview_truncated': True}
    for task in records:
        if artifacts_only:
            task['steps'] = []
        if artifacts_only or not work.read_only_task(task):
            task.update(can_restore=False, can_retry_summary=False, can_retry_vision=False)
    return records


@router.get('/uploads')
def uploads(work=Depends(service)):
    return work.store.list_uploads()


@router.get('/tasks/{task_id}', response_model=FileTaskOut)
def task(task_id: str, work=Depends(service)):
    return public_task(invoke(work.task, task_id))


@router.post('/tasks/{task_id}/cancel', response_model=FileTaskOut)
def cancel(task_id: str, work=Depends(service)):
    return invoke(work.cancel, task_id)


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
    check_read_task(work, task_id)
    return invoke(work.approve_vision, task_id, payload.approved, payload.profile_id, payload.signature)


@router.get('/events')
def events(after: int | None = Query(default=None, ge=0), work=Depends(service)):
    return work.store.work_events(after)


def check_read_task(work, task_id):
    task = invoke(work.task, task_id)
    if not work.read_only_task(task):
        raise HTTPException(409, '旧办公任务不再执行；历史成果仍可下载。')


@router.post('/tasks/{task_id}/continue', response_model=FileTaskOut)
def continue_task(task_id: str, payload: ApprovalRequest, work=Depends(service)):
    check_read_task(work, task_id)
    return invoke(work.continue_task, task_id, payload.approved)


@router.post('/tasks/{task_id}/retry-summary', response_model=FileTaskOut)
def retry_summary(task_id: str, payload: RetrySummaryRequest, work=Depends(service)):
    check_read_task(work, task_id)
    return invoke(work.retry_summary, task_id, payload.extend_timeout)


@router.post('/tasks/{task_id}/retry-vision', response_model=FileTaskOut)
def retry_vision(task_id: str, work=Depends(service)):
    check_read_task(work, task_id)
    return invoke(work.retry_read_task, task_id, vision=True)


def download_response(item, data):
    return Response(
        data,
        media_type='application/octet-stream',
        headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(item['name']),
            'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'no-store',
        },
    )


@router.get('/files/{attachment_id}')
def download_attachment(attachment_id: str, work=Depends(service)):
    from ..work_artifacts import attachment_bytes

    return download_response(*invoke(attachment_bytes, work, attachment_id))


@router.get('/files/{attachment_id}/preview')
def preview_attachment(attachment_id: str, work=Depends(service), full_size: bool = False):
    from .. import document_readers
    from ..work_artifacts import attachment_bytes

    item, data = invoke(attachment_bytes, work, attachment_id)
    try:
        if item['name'].lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tif', '.tiff')):
            return Response(
                document_readers.image_bytes(data, full_size=full_size),
                media_type='image/jpeg',
                headers={'Cache-Control': 'no-store'},
            )
        result, _ = document_readers.extract(data, item['name'], text_only=True)
    except (document_readers.DocumentError, OSError, ValueError) as error:
        raise HTTPException(422, str(error))
    return {'text': '\n'.join(block['text'] for block in result['blocks']), 'warnings': result['warnings']}


@router.get('/artifacts/{task_id}')
def download_artifact(task_id: str, work=Depends(service)):
    from ..work_artifacts import artifact_bytes

    return download_response(*invoke(artifact_bytes, work, task_id))
