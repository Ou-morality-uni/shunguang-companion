"""Preserve invalid private configuration before allowing explicit recovery."""

import json
from threading import RLock
from uuid import uuid4

LOCK = RLock()
warnings = {}


def quarantine(path):
    with LOCK:
        if path.exists():
            path.replace(path.with_name(path.name + '.corrupt-' + uuid4().hex))
        warnings[str(path)] = '配置损坏，已保留原文件副本，请重新填写并保存设置。'
    return {}


def read_object(path):
    with LOCK:
        if not path.exists():
            return {}
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(record, dict):
                raise ValueError('Configuration must be an object')
            return record
        except (ValueError, UnicodeError):
            return quarantine(path)
