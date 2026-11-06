"""Bounded search cache and atomic daily request budget; never store API keys."""

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config


@contextmanager
def database():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.DATA_DIR / 'search.sqlite3', timeout=5)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY, used INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, stamp REAL, value TEXT)')
        yield db
        db.commit()
    finally:
        db.close()


def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


def usage():
    with database() as db:
        row = db.execute('SELECT used FROM usage WHERE day=?', (today(),)).fetchone()
    return {'day': today(), 'used': row[0] if row else 0, 'timezone': 'Asia/Shanghai'}


def reserve(limit):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        day = today()
        db.execute('INSERT OR IGNORE INTO usage VALUES (?,0)', (day,))
        changed = db.execute('UPDATE usage SET used=used+1 WHERE day=? AND used<?', (day, limit)).rowcount
        db.execute('DELETE FROM usage WHERE day NOT IN (SELECT day FROM usage ORDER BY day DESC LIMIT 7)')
        return bool(changed)


def cached(key, seconds):
    if not seconds:
        return None
    with database() as db:
        row = db.execute('SELECT value FROM cache WHERE key=? AND stamp>?', (key, time.time() - seconds)).fetchone()
    return {**json.loads(row[0]), 'cached': True} if row else None


def remember(key, result):
    value = json.dumps(result, ensure_ascii=False)
    if len(value.encode()) > 128000:
        return
    with database() as db:
        db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key, time.time(), value))
        db.execute('DELETE FROM cache WHERE key NOT IN (SELECT key FROM cache ORDER BY stamp DESC LIMIT 64)')
