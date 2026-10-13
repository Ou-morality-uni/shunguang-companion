"""Local RAG administration. Stop the app before opening the same Qdrant store."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import rag

parser = argparse.ArgumentParser()
parser.add_argument('command', choices=['status', 'build', 'rebuild', 'search', 'probe'])
parser.add_argument('query', nargs='?', default='')
parser.add_argument('--spoilers', action='store_true')
args = parser.parse_args()
try:
    if args.command in ('build', 'rebuild'):
        result = rag.rebuild(force=args.command == 'rebuild')
    elif args.command == 'search':
        result = rag.search(args.query, allow_spoilers=args.spoilers)
    else:
        result = getattr(rag, args.command)()
    print(json.dumps(result, ensure_ascii=True, indent=2))
except rag.RagError as exc:
    print(json.dumps({'error': str(exc)}, ensure_ascii=True))
    raise SystemExit(1)
finally:
    rag.close()
