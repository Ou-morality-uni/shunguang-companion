"""Synthetic Linux UI preview. No real accounts, credentials or model calls."""

import argparse
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=18175)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='server-ui-') as temporary:
        root = Path(temporary)
        key = root / 'master.key'
        key.write_bytes(Fernet.generate_key())
        key.chmod(0o600)
        os.environ.update(
            SHUNGUANG_MODE='server',
            SHUNGUANG_DATA_DIR=str(root / 'data'),
            SHUNGUANG_MASTER_KEY_FILE=str(key),
            SHUNGUANG_LAN_MODE='1',
        )
        import uvicorn

        from backend.app import access, config, memory_jobs, runtime
        from backend.app import main as application
        from backend.app.qq.models import Policy
        from backend.app.routes import chat

        config.DATA_DIR.mkdir()
        access.save_password('offline-preview-password')
        config.save_config(
            config.ModelConfig(
                llm_base_url='https://example.invalid/v1',
                llm_model='离线界面验收',
                llm_api_key='synthetic-not-real-key',
            )
        )

        def no_model(*args):
            raise RuntimeError('UI preview never calls providers')

        memory_jobs.build_memory_model = no_model
        chat.build_model = no_model
        original = application.lifespan

        @asynccontextmanager
        async def fixture(app):
            async with original(app):
                runtime.qq.repo.save_peers('private', [{'user_id': 30001, 'nickname': '模拟联系人'}])
                runtime.qq.repo.save_policy('private', '30001', Policy(collect=True, chat='mention'))
                yield

        application.app.router.lifespan_context = fixture
        uvicorn.run(application.app, host=args.host, port=args.port, access_log=False)


if __name__ == '__main__':
    main()
