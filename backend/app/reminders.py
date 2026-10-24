"""Foreground polling scheduler with durable delivery and no offline backlog."""

import json
import os
import secrets
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
REMINDER_PHRASES = (
    REMINDER_TEXT,
    '手边的事先放一放呀，看看远处，让眼睛也透口气。我在这里等你。',
    '坐了这么久，起来伸个懒腰吧。事情可以慢慢做，咱们也要照顾好自己。',
    '杯子还在手边吗？喝两口水再继续吧，我陪你把剩下的慢慢理清。',
    '专心的时候容易忘了歇一歇。松松肩膀，活动一下手腕，好不好？',
    '这一小段先告个段落吧，起身走两步，回来再接着聊。',
    '别总盯着屏幕啦，眨眨眼，看看窗外。留一点精神，后面的路还长着呢。',
    '忙归忙，也给自己留口喘气的工夫呀。休息一会儿，我替你守着这些思路。',
)


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


def weather_message(value):
    current = value['current']
    city = value.get('location', {}).get('city') or value['profile_city']
    condition = value.get('condition', '天气状况待核对')
    temperature = float(current['temperature_2m'])
    if float(current.get('precipitation') or 0) > 0 or any(word in condition for word in ('雨', '雪', '雷')):
        advice = '出门记得带好雨具，路上慢一点呀。'
    elif temperature >= 30:
        advice = '外面有些热，出门记得遮阳，也别忘了补水。'
    elif temperature <= 10:
        advice = '外面偏凉，出门记得添件衣服，别让自己冻着。'
    elif float(current.get('wind_speed_10m') or 0) >= 30:
        advice = '外面风有些大，出门留意一下，咱们稳稳当当地走。'
    else:
        advice = '忙完也给自己留点休息的工夫，喝口水，再慢慢来。'
    return f'{city}这次查到的是{condition}，气温约{temperature:g}℃。{advice}'


def poll(*, immediate=False, weather_care=None, refresh_weather=False):
    with LOCK:
        features = load()
        settings = features.reminders
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
        weather = None
        if (
            weather_care
            and features.tools.weather_enabled
            and (immediate or (settings.enabled and not paused and not in_quiet))
        ):
            weather = weather_care.snapshot(features.tools.timeout, force=refresh_weather or reconnected)
        event = None
        if immediate or (settings.enabled and not paused and not in_quiet and not reconnected and now >= due):
            recent = state.get('recent_phrases', [])
            text = secrets.choice([item for item in REMINDER_PHRASES if item not in recent] or REMINDER_PHRASES)
            state['recent_phrases'] = (recent + [text])[-4:]
            event = {
                'id': uuid.uuid4().hex,
                'text': text,
                'voice': settings.voice,
                'created_at': timestamp(now),
                'test': immediate,
            }
            if weather:
                signature = weather['profile_city'] + '|' + weather['current']['time']
                if signature != state.get('last_weather'):
                    event['text'] = weather_message(weather)
                    event['weather'] = {
                        'city': weather['profile_city'],
                        'observed_at': weather['current']['time'],
                        'sources': weather.get('sources', []),
                    }
                    state['last_weather'] = signature
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
            'weather_notice': weather_care.notice if weather_care else '',
            'notice': '休息提醒按时间间隔触发，不检测姿态。页面前台轮询时可靠；后台受浏览器节流限制。关闭页面不提醒，恢复连接后不补发历史提醒。立即测试会忽略开关和安静时段。',
        }
