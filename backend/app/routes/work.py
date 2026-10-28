"""Local-only controls. Models cannot grant folders or approve destructive steps."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .. import runtime
from ..annotations import AnnotationRequest, CommentUpdate
from ..filework import MAX_FILE_BYTES, FileTaskRequest, WorkError, local_request, public_task
from ..schemas import DocumentUploadOut, FileTaskOut, WorkspaceOut


def service(request: Request):
    if not local_request(request):
        raise HTTPException(403, '工作台仅供运行服务的本机使用，局域网登录不会获得本机文件权限。')
    if runtime.work is None:
        raise HTTPException(503, '工作台尚未就绪。')
    return runtime.work


router = APIRouter(prefix='/api/work', dependencies=[Depends(service)])


@router.get('/capabilities')
def file_capabilities():
    from ..office_runtime import capabilities

    return capabilities()


from ..office_tasks import OfficeRequest


@router.post('/office/tasks', status_code=201, response_model=FileTaskOut)
def submit_office(payload: OfficeRequest, work=Depends(service)):
    from ..office_tasks import submit

    return invoke(submit, work, payload)


class GrantRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=1000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approved: bool


class RetrySummaryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    extend_timeout: bool = False


class ArtifactVersionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: str = Field(pattern=r'^[0-9a-f]{64}$')


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
def tasks(
    conversation_id: str | None = Query(default=None, max_length=80), compact: bool = False, work=Depends(service)
):
    records = [public_task(task) for task in work.store.list_file_tasks(conversation_id=conversation_id)]
    if compact:
        for task in records:
            for step in task['steps']:
                result = step.get('result')
                if result and len(result.get('blocks', [])) > 30:
                    step['result'] = {**result, 'blocks': result['blocks'][:30], 'preview_truncated': True}
    return records


@router.get('/uploads')
def uploads(work=Depends(service)):
    return work.store.list_uploads()


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


@router.get('/output')
def output(work=Depends(service)):
    workspace = invoke(work.default_output_workspace)
    return {
        'workspace': {key: workspace[key] for key in ('id', 'path', 'enabled', 'created_at')} if workspace else None
    }


@router.post('/output')
def choose_output(payload: GrantRequest, work=Depends(service)):
    workspace = invoke(work.grant, payload.path)
    work.store.set_output_workspace(workspace['id'])
    return output(work)


@router.post('/tasks/{task_id}/continue', response_model=FileTaskOut)
def continue_task(task_id: str, payload: ApprovalRequest, work=Depends(service)):
    return invoke(work.continue_task, task_id, payload.approved)


@router.post('/tasks/{task_id}/retry-summary', response_model=FileTaskOut)
def retry_summary(task_id: str, payload: RetrySummaryRequest, work=Depends(service)):
    return invoke(work.retry_summary, task_id, payload.extend_timeout)


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


@router.get('/artifacts/{task_id}')
def download_artifact(task_id: str, work=Depends(service)):
    from ..work_artifacts import artifact_bytes

    return download_response(*invoke(artifact_bytes, work, task_id))


@router.post('/artifacts/{task_id}/reveal')
def reveal_artifact(task_id: str, payload: ArtifactVersionRequest, work=Depends(service)):
    from ..work_artifacts import reveal

    return invoke(reveal, work, task_id, payload.version)


@router.get('/artifacts/{task_id}/thumbnail')
def artifact_thumbnail(task_id: str, version: str = Query(pattern=r'^[0-9a-f]{64}$'), work=Depends(service)):
    from ..office_resources import thumbnail

    return Response(
        invoke(thumbnail, work, task_id, version),
        media_type='image/jpeg',
        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'},
    )


@router.get('/artifacts/{task_id}/preview')
def preview_artifact(task_id: str, start: int = Query(default=1, ge=1, le=1000000), work=Depends(service)):
    from .. import document_readers
    from ..work_artifacts import artifact_bytes

    item, data = invoke(artifact_bytes, work, task_id)
    try:
        result, _ = document_readers.extract(data, item['name'], start, 5)
        result['version'] = item['sha256']
        result['validation'] = item.get('validation', {})
        return result
    except document_readers.DocumentError as error:
        raise HTTPException(422, str(error))


@router.get('/resources/{kind}/{resource_id}/targets')
def resource_targets(kind: str, resource_id: str, work=Depends(service)):
    from ..office_resources import targets

    return invoke(targets, work, kind, resource_id)


@router.get('/resources/{kind}/{resource_id}/info')
def resource_info(kind: str, resource_id: str, work=Depends(service)):
    from ..office_resources import resource_bytes

    item, _ = invoke(resource_bytes, work, kind, resource_id)
    return {'version': item['version'], 'name': item['name'], 'targets': []}


@router.get('/resources/{kind}/{resource_id}/pages')
def resource_pages(
    kind: str,
    resource_id: str,
    version: str | None = Query(default=None, pattern=r'^[0-9a-f]{64}$'),
    work=Depends(service),
):
    from ..office_resources import page_info

    return invoke(page_info, work, kind, resource_id, version)


@router.get('/resources/{kind}/{resource_id}/document')
def resource_document(
    kind: str,
    resource_id: str,
    version: str = Query(pattern=r'^[0-9a-f]{64}$'),
    work=Depends(service),
):
    from ..office_resources import preview_pdf

    data = invoke(preview_pdf, work, kind, resource_id, version)
    return Response(
        data,
        media_type='application/pdf',
        headers={
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
        },
    )


@router.get('/resources/{kind}/{resource_id}/image')
def resource_image(
    kind: str,
    resource_id: str,
    page: int = Query(default=1, ge=1),
    version: str | None = Query(default=None, pattern=r'^[0-9a-f]{64}$'),
    work=Depends(service),
):
    from ..office_resources import page_image

    data = invoke(page_image, work, kind, resource_id, page, version)
    return Response(
        data, media_type='image/jpeg', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
    )


@router.get('/annotations')
def annotation_drafts(
    conversation_id: str | None = Query(default=None, max_length=80),
    draft_scope: str = Query(default='', max_length=80),
    work=Depends(service),
):
    from .. import annotations

    return annotations.list_drafts(work.store, conversation_id, draft_scope)


@router.post('/annotations', status_code=201)
def add_annotation(payload: AnnotationRequest, work=Depends(service)):
    from .. import annotations

    return invoke(annotations.create, work.store, work, payload)


@router.patch('/annotations/{annotation_id}')
def edit_annotation(annotation_id: str, payload: CommentUpdate, work=Depends(service)):
    from .. import annotations

    return invoke(annotations.update, work.store, annotation_id, payload.comment)


@router.delete('/annotations/{annotation_id}')
def delete_annotation(annotation_id: str, work=Depends(service)):
    from .. import annotations

    return invoke(annotations.update, work.store, annotation_id, None, True)


@router.get('/files/{attachment_id}/preview')
def preview_attachment(attachment_id: str, start: int = Query(default=1, ge=1, le=1000000), work=Depends(service)):
    from .. import document_readers
    from ..work_artifacts import attachment_bytes

    item, data = invoke(attachment_bytes, work, attachment_id)
    try:
        result, _ = document_readers.extract(data, item['name'], start, 5)
        result['warnings'].append(
            '这是本机提取的内容预览，未调用聊天或视觉模型；复杂排版与图像解读以原文件及任务结果为准。'
        )
        return result
    except document_readers.DocumentError as error:
        raise HTTPException(422, str(error))


@router.get('/files/{attachment_id}/image')
def image_preview(attachment_id: str, page: int = Query(default=1, ge=1), work=Depends(service)):
    import io
    from pathlib import Path

    from .. import document_readers
    from ..work_artifacts import attachment_bytes

    item, data = invoke(attachment_bytes, work, attachment_id)
    try:
        if Path(item['name']).suffix.lower() == '.pdf':
            import pypdfium2 as pdfium

            with document_readers.PDF_LOCK, pdfium.PdfDocument(data) as document:
                if page > len(document):
                    raise HTTPException(422, '页码超出文档范围。')
                pdf_page = document[page - 1]
                bitmap = None
                try:
                    width, height = pdf_page.get_size()
                    bitmap = pdf_page.render(scale=min(1.8, 1600 / max(width, height)))
                    output = io.BytesIO()
                    bitmap.to_pil().convert('RGB').save(output, format='JPEG')
                    data = output.getvalue()
                finally:
                    if bitmap:
                        bitmap.close()
                    pdf_page.close()
        else:
            data = document_readers.image_bytes(data)
        return Response(
            data, media_type='image/jpeg', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
        )
    except (OSError, ValueError, document_readers.DocumentError):
        raise HTTPException(422, '无法生成此文件的图像预览。')
