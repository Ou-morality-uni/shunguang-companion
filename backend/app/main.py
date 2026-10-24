"""Composition root: startup, common protection, routers and static assets."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import access, runtime
from .config import ROOT
from .constants import MAX_MESSAGE_LENGTH, VERSION
from .filework import FileWork
from .logging_setup import report_error, setup_logging
from .memory_jobs import MemoryJobs
from .routes import chat, knowledge, memories, settings, work
from .schemas import CapabilitiesOut
from .services import router as services_router
from .weather_care import WeatherCare


@asynccontextmanager
async def lifespan(app):
    setup_logging()
    runtime.mutation_lock = asyncio.Lock()
    await asyncio.to_thread(runtime.store.initialize)
    runtime.work = await asyncio.to_thread(FileWork, runtime.store)
    runtime.weather_care = WeatherCare(runtime.store)
    runtime.memory_jobs = MemoryJobs(runtime.store)
    try:
        yield
    finally:
        await asyncio.to_thread(runtime.memory_jobs.close)
        runtime.memory_jobs = None
        await asyncio.to_thread(runtime.weather_care.close)
        runtime.weather_care = None
        await asyncio.to_thread(runtime.work.close)
        runtime.work = None


app = FastAPI(title='瞬光伴行 API', version=VERSION, lifespan=lifespan)
app.middleware('http')(access.guard)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    return JSONResponse(status_code=422, content={'detail': '输入格式不正确，请检查字段类型、长度和数值范围。'})


@app.exception_handler(Exception)
async def unhandled_error(request, error):
    report_error('unhandled', error)
    return JSONResponse(status_code=500, content={'detail': '服务内部错误，请查看后端日志。'})


@app.get('/api/capabilities', response_model=CapabilitiesOut)
def capabilities():
    return {'max_message_length': MAX_MESSAGE_LENGTH}


for router in (settings.router, chat.router, memories.router, knowledge.router, work.router, services_router):
    app.include_router(router)

dist = ROOT / 'frontend' / 'dist'
if (dist / 'assets').is_dir():
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(dist / 'index.html')
