"""Initialize empty local storage and verify real local retrieval."""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def application():
    from app.store import Store
    import imageio_ffmpeg
    database = ROOT / 'data/companion.sqlite3'
    required = {'conversations', 'messages', 'memories', 'memory_candidates'}
    if database.exists():
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(tables):
            raise RuntimeError('Existing database is incomplete; it was not overwritten')
        action = 'existing_database_preserved'
    else:
        Store(database).initialize()
        action = 'created_empty_database'
    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if subprocess.run([str(ffmpeg), '-version'], capture_output=True, timeout=15).returncode:
        raise RuntimeError('Bundled FFmpeg did not run')
    for name in ('character/avatar.png', 'character/stickers/10-red-pat.png',
                 'assets/ye-shunguang/warm-dawn-full-body.webp', 'voice/ye-shunguang/reference-original.mp3'):
        if not (ROOT / 'source/resources' / name).is_file():
            raise RuntimeError('Missing bundled resource: ' + name)
    return {'database': 'data/companion.sqlite3', 'database_action': action,
            'tables': sorted(required), 'ffmpeg': ffmpeg.name, 'resources_present': True}


def retrieval():
    import torch
    import transformers
    from app.rag import LocalIndex
    index = LocalIndex(ROOT / 'data')
    runtime = ROOT / '.venv-rag/rag-runtime.json'
    try:
        probe = index.probe()
        result = index.rebuild()
        if result['warnings']:
            raise RuntimeError('Bundled knowledge files have missing files or hash mismatches')
        sources = index.search('叶瞬光属于哪个阵营？')
        if not sources or not any('云岿山' in item['text'] for item in sources):
            raise RuntimeError('Bundled knowledge retrieval check failed')
        runtime.write_text(json.dumps({'verified': True, 'torch': torch.__version__,
                                      'transformers': transformers.__version__, 'device': probe['device']}, indent=2), encoding='utf-8')
        return {'probe': probe, 'index': result, 'retrieval_check': True}
    except Exception:
        runtime.write_text('{"verified": false}', encoding='utf-8')
        raise
    finally:
        index.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('application', 'retrieval'))
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = application() if args.mode == 'application' else retrieval()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True), flush=True)
