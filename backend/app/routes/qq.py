import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from .. import document_models, runtime
from ..config import local_knowledge_enabled, server_mode
from ..model_choices import public_choice
from ..qq import profiles
from ..qq.members import MemberPage, roster
from ..qq.models import Connection, Policy, SummaryRequest
from ..qq.repository import identifier
from ..qq.summaries import deliver

router = APIRouter(prefix='/api/qq', tags=['qq'])
Kind = Literal['private', 'group']


class QQState(BaseModel):
    connection: Connection
    has_token: bool
    status: str
    error: str
    owner: str
    last_event: float | None
    policies: list[dict]
    vision_profiles: list[dict]
    chat_view_ready: bool = True
    sticker_controls_ready: bool = True
    manual_profiles_ready: bool = True
    local_knowledge: bool = True
    deployment_mode: Literal['desktop', 'server'] = 'desktop'


class BindingOut(BaseModel):
    code: str
    expires: float


class StickerSwitch(BaseModel):
    enabled: bool


class PeerPage(BaseModel):
    items: list[dict]
    total: int


def service():
    if runtime.qq is None:
        raise HTTPException(503, 'QQ 后台尚未启动')
    return runtime.qq


def valid_target(value):
    try:
        return identifier(value)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


def profile_action(action):
    try:
        return action()
    except profiles.ProfileConflict as error:
        raise HTTPException(409, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.get('/profiles/{kind}/{target}', response_model=profiles.ProfileOut)
def profile_get(kind: Kind, target: str, subject: str = Query(default='', max_length=20)):
    return profile_action(lambda: profiles.read(service().repo, kind, target, subject))


@router.put('/profiles/{kind}/{target}', response_model=profiles.ProfileOut)
def profile_put(
    kind: Kind, target: str, payload: profiles.ProfileUpdate, subject: str = Query(default='', max_length=20)
):
    return profile_action(lambda: profiles.write(service().repo, kind, target, subject, payload))


@router.delete('/profiles/{kind}/{target}', response_model=profiles.ProfileOut)
def profile_delete(
    kind: Kind, target: str, revision: int = Query(ge=0), subject: str = Query(default='', max_length=20)
):
    return profile_action(
        lambda: profiles.write(service().repo, kind, target, subject, profiles.ProfileUpdate(revision=revision))
    )


@router.get('/state', response_model=QQState)
def state():
    active = service()
    return {
        'connection': active.repo.connection(),
        'has_token': bool(active.repo.get('connection', {}).get('token_encrypted')),
        'status': active.status,
        'error': active.error,
        'owner': active.repo.get('owner', ''),
        'last_event': active.last_event,
        'policies': active.repo.policies(),
        'vision_profiles': document_models.profiles(),
        'local_knowledge': local_knowledge_enabled(),
        'deployment_mode': 'server' if server_mode() else 'desktop',
    }


@router.get('/members/{target}', response_model=MemberPage)
async def members(
    target: str,
    search: str = Query(default='', max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    refresh: bool = False,
):
    return await roster(service(), valid_target(target), search, offset, limit, refresh)


@router.patch('/connection', response_model=QQState)
async def connection(payload: Connection):
    active = service()
    try:
        if payload.model_choice:
            public_choice(payload.model_choice.model_dump())
        active.repo.save_connection(payload)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    await active.reconnect()
    return state()


@router.post('/binding', response_model=BindingOut)
def binding():
    return service().binding_code()


@router.delete('/binding', response_model=dict)
def unbind():
    service().unbind()
    return {'ok': True}


@router.post('/refresh', response_model=dict)
async def refresh():
    try:
        await service().refresh_peers()
        return {'ok': True}
    except Exception:
        raise HTTPException(409, '列表刷新失败，请确认 QQ 已连接且桥接支持好友和群列表接口') from None


@router.get('/peers/{kind}', response_model=PeerPage)
def peers(
    kind: Kind,
    search: str = Query(default='', max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
):
    repo = service().repo
    known = {item['target']: item for item in repo.peers(kind)}
    with repo.connect() as db:
        for row in db.execute(
            'SELECT DISTINCT target FROM events WHERE bot=? AND kind=? UNION SELECT target FROM manual_profiles WHERE bot=? AND kind=? AND json_array_length(value)>0 UNION SELECT target FROM policies WHERE kind=?',
            (repo.connection().bot_id, kind, repo.connection().bot_id, kind, kind),
        ):
            known.setdefault(row['target'], {'kind': kind, 'target': row['target'], 'name': row['target']})
    items = sorted(
        (item for item in known.values() if search.lower() in (item['name'] + item['target']).lower()),
        key=lambda item: (item['name'], item['target']),
    )
    return {
        'items': [
            {**item, 'policy': repo.policy(kind, item['target']).model_dump()}
            for item in items[offset : offset + limit]
        ],
        'total': len(items),
    }


@router.put('/policies/{kind}/{target}', response_model=Policy)
def policy(kind: Kind, target: str, payload: Policy):
    active = service()
    valid_target(target)
    if kind == 'private' and (payload.schedule != 'off' or payload.allow_group_send or payload.delivery != 'panel'):
        raise HTTPException(422, '私聊不能设置群总结计划或群投递许可')
    if payload.images and document_models.selected(payload.vision_profile, payload.vision_signature) is None:
        raise HTTPException(422, '请选择已验证的视觉配置，并明确开启当前范围的图片处理授权')
    active.repo.save_policy(kind, target, payload)
    active.wake()
    return payload


@router.get('/policies/{kind}/{target}', response_model=Policy)
def get_policy(kind: Kind, target: str):
    return service().repo.policy(kind, valid_target(target))


@router.post('/summaries/{target}', response_model=dict)
def summary(target: str, payload: SummaryRequest):
    if payload.end > time.time() + 60:
        raise HTTPException(422, '手动总结结束时间不能在未来')
    try:
        return service().repo.queue_summary(valid_target(target), payload.start, payload.end, payload.delivery)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.get('/summaries', response_model=list[dict])
def summaries():
    return service().repo.summaries()


@router.delete('/summaries/{key}', response_model=dict)
def delete_summary(key: str):
    repo = service().repo
    job = repo.summary(key)
    if job and (job['state'] == 'generating' or job['sent'] == 'sending'):
        raise HTTPException(409, '任务处理中，请完成后再删除')
    repo.delete_summary(key)
    return {'ok': True}


@router.post('/summaries/{key}/retry', response_model=dict)
def retry_summary(key: str):
    repo = service().repo
    job = repo.summary(key)
    if not job:
        raise HTTPException(404, '摘要不存在')
    if job['state'] != 'failed':
        raise HTTPException(409, '只有生成失败的摘要可重试；已有摘要请使用投递按钮')
    repo.summary_state(key, 'queued')
    return repo.summary(key)


@router.post('/summaries/{key}/deliver', response_model=dict)
async def retry_delivery(key: str):
    active = service()
    job = active.repo.summary(key)
    if not job:
        raise HTTPException(404, '摘要不存在')
    if job['sent'] in ('sending', 'uncertain'):
        raise HTTPException(409, '发送结果待确认。请先在 QQ 核对；本版不自动重发，避免重复消息')
    await deliver(active, job)
    return active.repo.summary(key)


@router.get('/scopes', response_model=list[dict])
def scopes():
    return service().repo.scopes()


def scoped_store(key):
    active = service()
    if not any(item['key'] == key for item in active.repo.scopes()):
        raise HTTPException(404, '作用域不存在')
    bot, kind, target, author, _ = key.split(':')
    # Admins may view an old scope, but rebinding must never remap it to the owner's database.
    if key.endswith(':owner'):
        return runtime.store
    import hashlib

    from ..store import Store

    return Store(active.repo.root / 'scopes' / (hashlib.sha256(key.encode()).hexdigest() + '.sqlite3'))


@router.get('/scope', response_model=dict)
def scope(key: str = Query(max_length=200)):
    store = scoped_store(key)
    refs = [item for item in service().repo.scopes() if item['key'] == key]
    conversation = refs[0]['conversation']
    return {
        'key': key,
        'conversation': conversation,
        'memories': store.list_memories(),
        'messages': store.messages(conversation, 100),
    }


@router.delete('/scope/memories/{memory_id}', response_model=dict)
def delete_memory(memory_id: str, key: str = Query(max_length=200)):
    return {'ok': scoped_store(key).delete_memory(memory_id)}


@router.delete('/scope/history', response_model=dict)
async def delete_history(key: str = Query(max_length=200)):
    active = service()
    store = scoped_store(key)
    conversation = next(item['conversation'] for item in active.repo.scopes() if item['key'] == key)
    async with runtime.mutation_lock:
        if conversation in runtime.busy:
            raise HTTPException(409, '对话处理中，请稍后重试')
        store.delete_conversation(conversation)
    return {'ok': True}


@router.get('/chats', response_model=dict)
def chats(search: str = Query(default='', max_length=100), offset: int = Query(default=0, ge=0)):
    active = service()
    with active.repo.connect() as db:
        rows = db.execute(
            'SELECT e.kind,e.target,MAX(e.stamp) AS stamp,COUNT(*) AS count,COALESCE(p.name,e.target) AS name '
            'FROM events e LEFT JOIN peers p ON p.kind=e.kind AND p.target=e.target WHERE e.bot=? '
            'GROUP BY e.kind,e.target HAVING COALESCE(p.name,e.target) LIKE ? OR e.target LIKE ? ORDER BY stamp DESC,e.kind,e.target',
            (active.repo.connection().bot_id, f'%{search}%', f'%{search}%'),
        ).fetchall()
    return {'items': [dict(row) for row in rows[offset : offset + 30]], 'total': len(rows)}


@router.patch('/chats/{kind}/{target}/stickers', response_model=Policy)
def chat_stickers(kind: Kind, target: str, payload: StickerSwitch):
    active = service()
    target = valid_target(target)
    # Patch just this field so concurrent edits cannot reset chat/vision/schedules.
    with active.repo.connect() as db:
        updated = db.execute(
            "UPDATE policies SET value=json_set(value,'$.stickers',json(?)) WHERE kind=? AND target=?",
            ('true' if payload.enabled else 'false', kind, target),
        ).rowcount
    if not updated:
        active.repo.save_policy(kind, target, Policy(stickers=payload.enabled))
    return active.repo.policy(kind, target)


@router.get('/chats/{kind}/{target}/images/{image_id}')
def chat_image(kind: Kind, target: str, image_id: str):
    active = service()
    with active.repo.connect() as db:
        row = db.execute(
            'SELECT images.data FROM images JOIN events ON images.event=events.id '
            'WHERE images.id=? AND events.kind=? AND events.target=? AND events.bot=?',
            (image_id, kind, valid_target(target), active.repo.connection().bot_id),
        ).fetchone()
    if not row or not row['data']:
        raise HTTPException(404, '图片副本不存在或已过期')
    return Response(
        row['data'], media_type='image/jpeg', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
    )


@router.get('/chats/{kind}/{target}', response_model=dict)
def chat_messages(
    kind: Kind,
    target: str,
    before: str = Query(default='', max_length=100),
    limit: int = Query(default=30, ge=1, le=100),
):
    import json

    active = service()
    bot, target = active.repo.connection().bot_id, valid_target(target)
    with active.repo.connect() as db:
        params = [bot, kind, target]
        condition = ''
        if before:
            anchor = db.execute(
                'SELECT stamp FROM events WHERE id=? AND bot=? AND kind=? AND target=?', (before, *params)
            ).fetchone()
            if not anchor:
                raise HTTPException(404, '分页位置不存在或已过期')
            condition = ' AND (stamp<? OR (stamp=? AND id<?))'
            params.extend([anchor['stamp'], anchor['stamp'], before])
        rows = db.execute(
            'SELECT * FROM events WHERE bot=? AND kind=? AND target=?'
            + condition
            + ' ORDER BY stamp DESC,id DESC LIMIT ?',
            (*params, limit + 1),
        ).fetchall()
        items = []
        for row in reversed(rows[:limit]):
            item = {key: row[key] for key in ('id', 'author', 'name', 'stamp', 'text', 'reply', 'state', 'error')}
            item['sticker'] = json.loads(row['reply_sticker']) if row['reply_sticker'] else None
            item['images'] = [
                {
                    'id': image['id'],
                    'url': f'/api/qq/chats/{kind}/{target}/images/{image["id"]}' if image['data'] else None,
                    'description': image['description'],
                    'error': image['error'],
                }
                for image in db.execute(
                    'SELECT id,data,description,error FROM images WHERE event=? ORDER BY id', (row['id'],)
                )
            ]
            items.append(item)
    return {
        'items': items,
        'next_cursor': items[0]['id'] if items else '',
        'has_more': len(rows) > limit,
        'stickers': active.repo.policy(kind, target).stickers,
    }


@router.get('/records/{kind}/{target}', response_model=list[dict])
def records(kind: Kind, target: str):
    active = service()
    values = active.repo.messages(
        active.repo.connection().bot_id, kind, valid_target(target), 0, 2e10, 100, newest=True
    )
    # Do not return temporary CDN credentials/URLs from the raw segment payload.
    result = []
    with active.repo.connect() as db:
        for item in values[-100:]:
            record = {k: item[k] for k in ('id', 'author', 'name', 'stamp', 'text', 'state', 'error')}
            errors = [
                row['error']
                for row in db.execute('SELECT error FROM images WHERE event=? AND error!=?', (item['id'], ''))
            ]
            record['error'] = '；'.join(filter(None, [record['error'], *dict.fromkeys(errors)]))
            result.append(record)
    return result


@router.delete('/records/{kind}/{target}', response_model=dict)
def clear_records(kind: Kind, target: str):
    active = service()
    valid_target(target)
    if active.repo.policy(kind, target).collect:
        raise HTTPException(409, '请先关闭该范围的采集，再清理原始记录')
    with active.repo.connect() as db:
        if db.execute(
            "SELECT 1 FROM events WHERE kind=? AND target=? AND state='processing'", (kind, target)
        ).fetchone():
            raise HTTPException(409, '仍有处理中的回复，请稍后重试')
        db.execute(
            'DELETE FROM images WHERE event IN (SELECT id FROM events WHERE kind=? AND target=?)', (kind, target)
        )
        db.execute('DELETE FROM events WHERE kind=? AND target=?', (kind, target))
    return {'ok': True}
