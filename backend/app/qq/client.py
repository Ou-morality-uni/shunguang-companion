import asyncio
import json
from uuid import uuid4

import websockets


class OneBotError(RuntimeError):
    pass


class OneBotClient:
    def __init__(self, url, token, receive):
        self.url, self.token, self.receive = url, token, receive
        self.ws = None
        self.reader = None
        self.pending = {}

    async def open(self):
        self.ws = await websockets.connect(
            self.url,
            additional_headers={'Authorization': 'Bearer ' + self.token},
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=2 * 1024 * 1024,
            proxy=None,
        )
        self.reader = asyncio.create_task(self.read())

    async def read(self):
        try:
            async for raw in self.ws:
                try:
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        continue
                    echo = payload.get('echo')
                    if isinstance(echo, str) and echo in self.pending:
                        future = self.pending[echo]
                        if not future.done():
                            future.set_result(payload)
                    elif 'post_type' in payload:
                        self.receive(payload)
                except (ValueError, TypeError):
                    continue
        finally:
            for pending in self.pending.values():
                if not pending.done():
                    pending.set_exception(OneBotError('QQ 连接中断；发送结果可能需要确认'))

    async def call(self, action, **params):
        if self.ws is None or self.reader is None or self.reader.done():
            raise OneBotError('QQ 尚未连接')
        if len(self.pending) >= 32:
            raise OneBotError('QQ 请求过多，请稍后再试')
        echo = uuid4().hex
        future = self.pending[echo] = asyncio.get_running_loop().create_future()
        try:
            await self.ws.send(json.dumps({'action': action, 'params': params, 'echo': echo}))
            result = await asyncio.wait_for(future, 20)
            if result.get('status') != 'ok' or result.get('retcode') != 0:
                raise OneBotError('QQ API 拒绝请求，请检查登录、目标权限与桥接日志')
            return result.get('data')
        finally:
            self.pending.pop(echo, None)

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.reader:
            await asyncio.gather(self.reader, return_exceptions=True)
