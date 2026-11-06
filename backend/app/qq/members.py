"""A short-lived roster cache; reading a roster never enables collection or replies."""

import asyncio
import json
import time
from typing import Literal

from pydantic import BaseModel

from .repository import identifier


class Member(BaseModel):
    user_id: str
    name: str
    card: str = ''
    source: Literal['bridge', 'captured', 'manual']


class MemberPage(BaseModel):
    items: list[Member]
    total: int
    stale: bool
    refreshed: float
    notice: str


async def roster(service, target, search='', offset=0, limit=30, refresh=False):
    repo = service.repo
    bot = repo.connection().bot_id
    key = f'members:{bot}:{target}'
    cached = repo.get(key, {'stamp': 0, 'items': []})
    stale = bool(cached.get('failed')) or time.time() - cached['stamp'] > 300
    if refresh or (stale and time.time() - cached.get('attempt', 0) > 5):
        try:
            if service.status != 'connected' or not service.client:
                raise ValueError('offline')
            async with asyncio.timeout(20):
                raw = await service.client.call('get_group_member_list', group_id=int(target))
            if not isinstance(raw, list) or len(raw) > 10000:
                raise ValueError('invalid roster')
            normalized = {}
            for item in raw:
                if not isinstance(item, dict):
                    raise ValueError('invalid member')
                uid = identifier(item.get('user_id'))
                normalized[uid] = Member(
                    user_id=uid,
                    name=str(item.get('nickname') or uid)[:200],
                    card=str(item.get('card') or '')[:200],
                    source='bridge',
                ).model_dump()
            cached = {'stamp': time.time(), 'items': list(normalized.values())}
            repo.put(key, cached)
            stale = False
        except Exception:
            # Preserve the last valid cache and every manual profile on bridge failure.
            stale = True
            cached.update(failed=True, attempt=time.time())
            repo.put(key, cached)
    items = {item['user_id']: item for item in cached['items']}
    with repo.connect() as db:
        for row in db.execute(
            "SELECT author,name,MAX(stamp) FROM events WHERE bot=? AND kind='group' AND target=? GROUP BY author",
            (bot, target),
        ):
            items.setdefault(
                row['author'],
                Member(user_id=row['author'], name=row['name'] or row['author'], source='captured').model_dump(),
            )
        for row in db.execute(
            "SELECT subject,value FROM manual_profiles WHERE bot=? AND kind='group' AND target=? AND subject!='' AND json_array_length(value)>0",
            (bot, target),
        ):
            entries = json.loads(row['value'])
            name = next((e['value'] for e in entries if e['key'] == 'name'), row['subject'])
            items.setdefault(row['subject'], Member(user_id=row['subject'], name=name, source='manual').model_dump())
    matches = sorted(
        (v for v in items.values() if search.casefold() in (v['name'] + v['card'] + v['user_id']).casefold()),
        key=lambda v: (v['card'] or v['name'], v['user_id']),
    )
    return MemberPage(
        items=matches[offset : offset + limit],
        total=len(matches),
        stale=stale,
        refreshed=cached['stamp'],
        notice='名单未刷新，使用缓存、已采集和手动建档成员；手动建档不代表仍在群内。'
        if stale
        else '名单来自桥接；手动建档不代表桥接确认仍在群内。',
    )
