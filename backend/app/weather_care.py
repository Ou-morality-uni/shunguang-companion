"""Weather refreshes are triggered by foreground polls, never by a permanent timer."""

import asyncio
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import RLock
from zoneinfo import ZoneInfo

from . import tools


class WeatherCare:
    def __init__(self, store):
        self.store = store
        self.lock = RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='weather-care')
        self.city = ''
        self.notice = ''
        self.data = None
        self.fetched_at = 0
        self.observed_at = 0
        self.attempted_at = 0
        self.pending = None
        self.closed = False

    def snapshot(self, timeout, *, force=False):
        city = self.store.user_profile()['city']
        with self.lock:
            if self.closed:
                return None
            changed = city != self.city
            if changed:
                self.city, self.data, self.attempted_at = city, None, 0
                self.notice = ''
                if self.pending:
                    self.pending.cancel()
            if not city:
                return None
            now = time.time()
            fresh = (
                self.data is not None and 0 <= now - self.fetched_at < 3600 and -300 <= now - self.observed_at <= 7200
            )
            pending = self.pending is not None and not self.pending.done()
            if (changed or not pending) and (force or changed or (not fresh and now - self.attempted_at >= 300)):
                self.attempted_at = now
                self.pending = self.pool.submit(self.refresh, city, timeout)
            return self.data if fresh else None

    def refresh(self, city, timeout):
        try:
            value = asyncio.run(
                asyncio.wait_for(tools.weather(tools.WeatherArgs(city=city), timeout), timeout=timeout * 4 + 1)
            )
            if not value.get('ok'):
                with self.lock:
                    if not self.closed and self.city == city and value.get('code') == 'ambiguous_location':
                        self.notice = '这个城市有同名地点，先到记忆空间补充省份或国家吧，我再帮你看看那边的天气。'
                return
            current = value.get('current', {})
            temperature = float(current['temperature_2m'])
            for key in ('precipitation', 'wind_speed_10m'):
                if current.get(key) is not None and not math.isfinite(float(current[key])):
                    return
            if not isinstance(value.get('condition', ''), str):
                return
            observed = datetime.fromisoformat(current['time'].replace('Z', '+00:00'))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=ZoneInfo(value.get('timezone') or 'UTC'))
            age = datetime.now(timezone.utc).timestamp() - observed.timestamp()
            if not math.isfinite(temperature) or not -300 <= age <= 7200:
                return
            with self.lock:
                if not self.closed and self.city == city:
                    self.data = {**value, 'profile_city': city}
                    self.notice = ''
                    self.fetched_at = time.time()
                    self.observed_at = observed.timestamp()
        except Exception:
            # A weather failure never fabricates conditions or stops ordinary care.
            return

    def close(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=True, cancel_futures=True)
