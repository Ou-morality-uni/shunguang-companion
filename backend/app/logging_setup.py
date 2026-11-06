"""Allowlisted diagnostics: never log exception text, request bodies or URLs."""

import json
import logging
import time
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

request_id = ContextVar('request_id', default='')
ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger('shunguang')


def setup_logging():
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def report_error(operation: str, error: Exception):
    status = getattr(error, 'status_code', None)
    stack = []
    frame = error.__traceback__
    while frame:
        path = Path(frame.tb_frame.f_code.co_filename)
        location = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else '<dependency>'
        stack.append({'file': location, 'line': frame.tb_lineno})
        frame = frame.tb_next
    logger.warning(
        json.dumps(
            {
                'request_id': request_id.get(),
                'operation': operation,
                'error_type': type(error).__name__,
                'status': status if isinstance(status, int) else None,
                'stack': stack[-24:],
            },
            ensure_ascii=False,
        )
    )


def metric(stage, duration, **values):
    logger.info(
        json.dumps(
            {'request_id': request_id.get(), 'stage': stage, 'duration_ms': round(duration * 1000, 2), **values},
            ensure_ascii=False,
        )
    )


class RequestTraceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        token = request_id.set(uuid4().hex)
        start = time.monotonic()
        status = None

        async def traced_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message = {
                    **message,
                    'headers': [*message.get('headers', []), (b'x-request-id', request_id.get().encode())],
                }
            await send(message)

        try:
            await self.app(scope, receive, traced_send)
        finally:
            metric('request', time.monotonic() - start, status=status)
            request_id.reset(token)
