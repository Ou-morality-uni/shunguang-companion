"""Own reservations even when an ASGI response is never consumed."""

import asyncio

import anyio
from fastapi.responses import StreamingResponse

START_TIMEOUT = 5.0


class ReservedResponse(StreamingResponse):
    """Claim on first iteration, or finish the abandoned turn without model work."""

    def __init__(self, content, abandoned, **kwargs):
        self.state = 'pending'
        self.abandoned = abandoned
        self.abandoned_event = ''
        self.expiry = asyncio.create_task(self.expire())

        async def consume():
            if self.state != 'pending':
                await asyncio.shield(self.expiry)
                yield self.abandoned_event
                return
            self.state = 'started'
            self.expiry.cancel()
            try:
                async for item in content:
                    yield item
            finally:
                await content.aclose()
                await asyncio.gather(self.expiry, return_exceptions=True)

        super().__init__(consume(), **kwargs)

    async def expire(self):
        await asyncio.sleep(START_TIMEOUT)
        await self.abandon()

    async def abandon(self):
        if self.state == 'pending':
            self.state = 'expired'
            self.abandoned_event = await self.abandoned()

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.abandon()
                if self.state == 'expired' and not self.expiry.done():
                    self.expiry.cancel()
                    await asyncio.gather(self.expiry, return_exceptions=True)
