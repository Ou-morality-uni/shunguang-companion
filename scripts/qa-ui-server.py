"""Local-only UI integration fixture. Separate temporary DB; never uses real APIs."""

import asyncio
import sys
import tempfile
from pathlib import Path

import uvicorn
from langchain_core.messages import AIMessageChunk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import config, main, rag, runtime, tools
from backend.app.routes import chat as chat_routes
from backend.app.store import Store


class PreviewModel:
    async def astream(self, messages):
        text = messages[-1].content
        await asyncio.sleep(0.5)
        if '失败' in text:
            yield AIMessageChunk(content='这是测试环境的部分回复。')
            await asyncio.sleep(0.3)
            raise RuntimeError('Simulated provider failure')
        chunks = [
            '你好，',
            '这是**界面联调**的模拟回复。\n\n',
            '中文流式消息正在通过原有 FastAPI SSE 接口，',
            '适配到 assistant-ui。\n\n',
            '- 停止回复\n- 会话切换\n- Markdown 渲染\n\n',
            '仅用于验证 UI，没有调用真实模型。',
        ]
        if '慢速' in text:
            chunks = ['慢速联调片段。'] * 80
        for chunk in chunks:
            await asyncio.sleep(0.3)
            yield AIMessageChunk(content=chunk)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='shunguang-ui-qa-') as folder:
        config.DATA_DIR = Path(folder)
        config.save_config(config.ModelConfig(llm_model='ui-test-only', llm_api_key='dummy-key-not-a-real-credential'))
        runtime.store = Store(Path(folder) / 'qa.sqlite3')
        chat_routes.build_model = lambda _: PreviewModel()
        tools.schemas = lambda _: []
        rag.status = lambda: {'ready': False}
        uvicorn.run(main.app, host='127.0.0.1', port=8001, access_log=False)
