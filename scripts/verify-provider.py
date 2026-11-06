"""Small real calls using UI-saved credentials; never print credentials/errors."""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import load_config, public_config
from backend.app.llm import build_model, extract_text, friendly_error
from backend.app.providers import discover


async def run():
    config = load_config()
    report = {'configuration': public_config(config), 'kind': 'real_api', 'checks': []}
    try:
        start = time.monotonic()
        result = await discover(config)
        report['checks'].append({'name': 'model_discovery', 'ok': bool(result['models']), 'models': result['models'], 'seconds': round(time.monotonic()-start, 3)})
        model = build_model(config)
        start = time.monotonic()
        result = await model.ainvoke('请只回复：连接成功。')
        report['checks'].append({'name': 'response', 'ok': bool(extract_text(result.content)), 'text': extract_text(result.content)[:120], 'seconds': round(time.monotonic()-start, 3)})
        start, first, text, count = time.monotonic(), None, '', 0
        async for chunk in model.astream('用中文说一句简短问候。'):
            delta = extract_text(chunk.content)
            if delta:
                first = first or time.monotonic()-start
                count += 1
                text += delta
        report['checks'].append({'name': 'stream', 'ok': bool(text), 'chunks': count, 'text': text[:150], 'first_text_seconds': round(first or 0,3), 'total_seconds': round(time.monotonic()-start,3)})
    except Exception as error:
        report['checks'].append({'name': 'failure', 'ok': False, 'message': friendly_error(error)})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return all(c['ok'] for c in report['checks'])


if __name__ == '__main__':
    raise SystemExit(0 if asyncio.run(run()) else 1)
