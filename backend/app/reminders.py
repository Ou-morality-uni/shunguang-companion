"""Foreground polling scheduler with durable delivery and no offline backlog."""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from threading import RLock
from zoneinfo import ZoneInfo

from . import config
from .feature_config import load

LOCK = RLock()
MAX_POLL_GAP = 90
REMINDER_TEXT = '陪你待了一会儿，先让眼睛歇一歇吧。喝口水，起身活动一下，再回来慢慢聊。'


def read_state():
    path = config.DATA_DIR / 'reminders-state.json'
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_state(state):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DATA_DIR / 'reminders-state.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def reset():
    with LOCK:
        write_state({})


def quiet(settings, now):
    local = datetime.fromtimestamp(now, ZoneInfo(settings.timezone))
    minute = local.hour * 60 + local.minute
    start = sum(x * scale for x, scale in zip(map(int, settings.quiet_start.split(':')), (60, 1)))
    end = sum(x * scale for x, scale in zip(map(int, settings.quiet_end.split(':')), (60, 1)))
    if start == end:
        return False
    return start <= minute < end if start < end else minute >= start or minute < end


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def poll(*, immediate=False):
    with LOCK:
        settings = load().reminders
        now = time.time()
        state = read_state()
        interval = settings.interval_minutes * 60
        previous_poll = state.get('last_poll')
        reconnected = previous_poll is None or now - previous_poll > MAX_POLL_GAP or now < previous_poll
        if reconnected:
            state['next_due'] = now + interval
        due = float(state.get('next_due', now + interval))
        paused = bool(
            settings.paused_until
            and datetime.fromisoformat(settings.paused_until.replace('Z', '+00:00')).timestamp() > now
        )
        in_quiet = quiet(settings, now)
        event = None
        if immediate or (settings.enabled and not paused and not in_quiet and not reconnected and now >= due):
            event = {
                'id': uuid.uuid4().hex,
                'text': REMINDER_TEXT,
                'voice': settings.voice,
                'created_at': timestamp(now),
                'test': immediate,
            }
            # Consume durably before returning. A dropped response is not replayed.
            state['last_event_id'] = event['id']
            state['last_delivery'] = now
            state['next_due'] = now + interval
        elif not settings.enabled or paused or in_quiet:
            state['next_due'] = now + interval
        state['last_poll'] = now
        write_state(state)
        return {
            'event': event,
            'next_due': timestamp(state.get('next_due', due)),
            'paused': paused,
            'quiet': in_quiet,
            'enabled': settings.enabled,
            'reconnected': reconnected,
            'notice': '休息提醒按时间间隔触发，不检测姿态。页面前台轮询时可靠；后台受浏览器节流限制。关闭页面不提醒，恢复连接后不补发历史提醒。立即测试会忽略开关和安静时段。',
        }
