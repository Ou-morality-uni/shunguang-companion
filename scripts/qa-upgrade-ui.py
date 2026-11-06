"""Isolated browser fixture for the maintenance upgrade; never contacts a provider."""

import sys
import tempfile
from pathlib import Path

import uvicorn
from langchain_core.messages import AIMessageChunk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import cloud_voices, config, feature_config, main, rag, runtime, tools
from backend.app.routes import chat
from backend.app.store import Store


class PreviewModel:
    async def astream(self, messages):
        yield AIMessageChunk(content='记得呀，贺州。今天想聊点什么？')


async def voices():
    return {
        'voices': [
            {
                'name': '联调声音一',
                'voice': 'qa-voice-one',
                'model': 'qwen3-tts-vc-realtime-2026-01-15',
                'created_at': '2026-10-16',
            },
            {
                'name': '联调声音二',
                'voice': 'qa-voice-two',
                'model': 'qwen3-tts-vc-realtime-2026-01-15',
                'created_at': '2026-10-16',
            },
        ]
    }


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='shunguang-upgrade-ui-') as folder:
        config.DATA_DIR = Path(folder)
        runtime.store = Store(config.DATA_DIR / 'qa.sqlite3')
        config.save_config(config.ModelConfig(llm_model='offline-preview', llm_api_key='dummy-not-a-real-key'))
        feature_config.update(
            {
                'tts': {
                    'provider': 'aliyun',
                    'base_url': 'https://dashscope.aliyuncs.com',
                    'model': 'qwen3-tts-vc-realtime-2026-01-15',
                    'api_key': 'dummy-not-a-real-key',
                    'external_reference_enabled': True,
                    'voice': 'qa-voice-one',
                }
            }
        )
        cloud_voices.list_voices = voices
        chat.build_model = lambda _: PreviewModel()
        tools.schemas = lambda _: []
        rag.status = lambda: {'ready': False}
        uvicorn.run(main.app, host='127.0.0.1', port=18155, access_log=False)
