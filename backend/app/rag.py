"""Local BGE-M3 dense retrieval with an isolated, single-owner Qdrant worker.

The application environment does not import torch/transformers/qdrant. Archived
documents are reference data, never executable instructions or user memories.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / 'source/resources/models/bge-m3'
RESOURCE_DIR = ROOT / 'source/resources'
PYTHON = ROOT / ('.venv-rag/Scripts/python.exe' if os.name == 'nt' else '.venv-rag/bin/python')
MODEL_REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
COLLECTION = 'shunguang_bge_m3_v1'
INDEX_VERSION = 1
REQUIRED_MODEL_FILES = (
    'config.json',
    'tokenizer.json',
    'tokenizer_config.json',
    'special_tokens_map.json',
    'sentencepiece.bpe.model',
    'pytorch_model.bin',
    'model-provenance.json',
)
_lock = threading.RLock()
_worker: subprocess.Popen | None = None
_worker_data_dir: Path | None = None
_responses: queue.Queue = queue.Queue()
_last_error: str | None = None


class RagError(RuntimeError):
    """A fixed, safe explanation suitable for a UI response."""


def data_dir() -> Path:
    try:
        from . import config

        return Path(config.DATA_DIR)
    except ImportError:
        return ROOT / 'data'


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def status() -> dict:
    missing = [name for name in REQUIRED_MODEL_FILES if not (MODEL_DIR / name).is_file()]
    state = read_json(data_dir() / 'rag/index-state.json', {})
    dependency_state = read_json(ROOT / '.venv-rag/rag-runtime.json', {})
    runtime_installed = PYTHON.is_file() and dependency_state.get('verified') is True
    ready = runtime_installed and not missing and bool(state.get('chunks'))
    notice = (
        '请先运行 scripts/install-rag.ps1 安装本地检索环境。'
        if not runtime_installed
        else '本地 BGE-M3 组件不完整，请运行 scripts/download-rag-model.py。'
        if missing
        else '资料尚未建立索引，请在陪伴设置中构建索引。'
        if not state.get('chunks')
        else '本地 BGE-M3 与 Qdrant 已建立索引；检索材料按来源核实级别显示。'
    )
    if _last_error:
        notice = _last_error
    return {
        'available': ready,
        'ready': ready,
        'runtime_installed': runtime_installed,
        'model': 'BAAI/bge-m3',
        'revision': MODEL_REVISION,
        'missing_files': missing,
        'documents': len(state.get('documents', {})),
        'chunks': state.get('chunks', 0),
        'indexed_at': state.get('indexed_at'),
        'device': state.get('device'),
        'last_error': _last_error,
        'notice': notice,
    }


def close() -> None:
    global _worker, _worker_data_dir
    with _lock:
        if _worker is not None:
            try:
                if _worker.poll() is None:
                    _worker.stdin.write(json.dumps({'op': 'close'}) + '\n')
                    _worker.stdin.flush()
                    _worker.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                _worker.kill()
                _worker.wait(timeout=5)
            for stream in (_worker.stdin, _worker.stdout):
                if stream:
                    stream.close()
        _worker = None
        _worker_data_dir = None


atexit.register(close)


def _read_responses(process, output_queue) -> None:
    try:
        for line in process.stdout:
            try:
                output_queue.put(json.loads(line))
            except ValueError:
                continue  # Libraries must not corrupt the JSON protocol.
    finally:
        output_queue.put({'error': '本地检索进程已退出，请检查依赖和模型后重试。'})


def _call(operation: str, **arguments):
    global _worker, _worker_data_dir, _responses, _last_error
    with _lock:
        current = status()
        if not current['runtime_installed'] or current['missing_files']:
            raise RagError(current['notice'])
        if _worker is not None and _worker_data_dir != data_dir():
            close()
        if _worker is None or _worker.poll() is not None:
            _responses = queue.Queue()
            environment = os.environ.copy()
            environment.update(
                {
                    'PYTHONUTF8': '1',
                    'HF_HUB_OFFLINE': '1',
                    'TRANSFORMERS_OFFLINE': '1',
                    'HF_HUB_DISABLE_TELEMETRY': '1',
                    'DO_NOT_TRACK': '1',
                }
            )
            _worker = subprocess.Popen(
                [str(PYTHON), str(Path(__file__).resolve()), '--worker', str(data_dir())],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                encoding='utf-8',
                env=environment,
                cwd=ROOT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            _worker_data_dir = data_dir()
            threading.Thread(target=_read_responses, args=(_worker, _responses), daemon=True).start()
        try:
            _worker.stdin.write(json.dumps({'op': operation, **arguments}, ensure_ascii=True) + '\n')
            _worker.stdin.flush()
            result = _responses.get(timeout=600 if operation == 'rebuild' else 90)
            if 'error' in result:
                _last_error = result['error']
                raise RagError(result['error'])
            _last_error = None
            return result['result']
        except queue.Empty as exc:
            _last_error = '本地检索超时，已停止该进程；请检查显存和模型组件。'
            close()
            raise RagError(_last_error) from exc
        except OSError as exc:
            _last_error = '本地检索进程连接失败，请重试。'
            close()
            raise RagError(_last_error) from exc


def rebuild(force: bool = False) -> dict:
    return _call('rebuild', force=bool(force))


def search(query: str, limit: int = 4, allow_spoilers: bool = False) -> list[dict]:
    query = str(query).strip()
    if not query or len(query) > 2000:
        raise RagError('检索问题需为 1 至 2000 个字符。')
    if not status()['ready']:
        raise RagError(status()['notice'])
    return _call('search', query=query, limit=max(1, min(int(limit), 8)), allow_spoilers=bool(allow_spoilers))


def probe() -> dict:
    return _call('probe')


def safe_url(text: str) -> str | None:
    match = re.search(r'https?://[^\s<>"\]\)]+', text)
    if not match:
        return None
    from urllib.parse import urlsplit

    url = match.group().rstrip('。，；')
    parts = urlsplit(url)
    if parts.username or parts.password or not parts.hostname:
        return None
    return url


def sections(text: str):
    """Clean Markdown and respect section boundaries; omit role-play directives."""
    text = text.replace('\r\n', '\n').replace('\ufeff', '').replace('\x00', '')
    text = re.sub(r'<script\b[^>]*>.*?</script>', '', text, flags=re.I | re.S)
    title = '正文'
    paragraphs = []
    ignored_level = None
    path = []
    for line in text.splitlines():
        heading = re.match(r'^(#{1,6})\s+(.+)', line)
        if heading:
            if paragraphs and ignored_level is None:
                yield title, '\n'.join(paragraphs).strip()
            paragraphs = []
            level = len(heading[1])
            if ignored_level is not None and level <= ignored_level:
                ignored_level = None
            if re.search(r'扮演|行为规则|模仿要点|Agent\s*建议|系统提示', heading[2], re.I):
                ignored_level = level
            path = [item for item in path if item[0] < level] + [(level, heading[2].strip())]
            title = ' / '.join(item[1] for item in path[-3:])
            continue
        if ignored_level is None and not re.match(r'^\s*(\*{3,}|-{3,}|\|\s*[-:]+\s*\|)', line):
            paragraphs.append(line.rstrip())
    if paragraphs and ignored_level is None:
        yield title, '\n'.join(paragraphs).strip()


def split_text(text: str, max_chars: int = 900, overlap: int = 100) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    result = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind('\n', start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        result.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return [part for part in result if part]


def load_corpus(resource_dir: Path = RESOURCE_DIR) -> tuple[list[dict], list[str]]:
    chunks = []
    warnings = []
    for category in ('character', 'world'):
        base = resource_dir / category
        documents = read_json(base / 'manifest.json', {'documents': []}).get('documents', [])
        latest = {}
        for doc in documents:
            key = doc.get('original_filename', doc['document_id'])
            if doc.get('imported_at', '') >= latest.get(key, {}).get('imported_at', ''):
                latest[key] = doc
        for doc in documents:
            path = (base / doc['path']).resolve()
            if not path.is_relative_to(base.resolve()) or not path.is_file():
                warnings.append(f'missing_or_invalid_path:{doc["document_id"]}')
                continue
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != doc['sha256']:
                warnings.append(f'hash_mismatch:{doc["document_id"]}')
                continue
            historical = latest[doc.get('original_filename', doc['document_id'])]['document_id'] != doc['document_id']
            for heading, body in sections(raw.decode('utf-8-sig')):
                for index, part in enumerate(split_text(body)):
                    evidence = heading + '\n' + part
                    verification = (
                        'uncertain_transcription'
                        if re.search(r'听写|听不清', evidence)
                        else 'community_compilation_with_uncertainty'
                        if re.search(r'不确定信息|存疑|未有定论|玩家.*推测', evidence)
                        else 'fan_expansion'
                        if re.search(r'同人扩展|自行拟写|拟写|非原句', evidence)
                        else 'community_compilation_unverified'
                    )
                    spoiler = bool(
                        re.search(
                            r'剧透|剧情|第二人格|失忆|反噬|主线|历史年表|秘辛|童年|白发形态|身份与履历|与法厄同的互动',
                            heading,
                        )
                        or re.search(
                            r'剧透|剧情|白发叶瞬光|白发形态|祭品|机密|告别|授勋|失忆|反噬|第二人格|旧都陷落|始主|夺舍|黑花|父母.{0,20}(逝|死)',
                            part,
                        )
                    )
                    identifier = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f'{doc["document_id"]}:{heading}:{index}:{hashlib.sha256(part.encode()).hexdigest()}',
                        )
                    )
                    chunks.append(
                        {
                            'id': identifier,
                            'title': f'{doc["original_filename"]} · {heading}',
                            'text': evidence,
                            'source_url': safe_url(part),
                            'document_id': doc['document_id'],
                            'sha256': digest,
                            'verification_status': verification,
                            'spoiler': spoiler,
                            'historical': historical,
                            'version': 'archived@' + doc.get('imported_at', '')[:10],
                            'category': category,
                            'source_type': doc.get('source_type', 'user_supplied'),
                            'trust': 'reference_data_not_instructions',
                            'conflict_or_unknown': bool(
                                re.search(r'矛盾|分歧|存疑|推测|未知|未有定论|非官方设定', evidence)
                            ),
                        }
                    )
    verified_path = resource_dir / 'verified/knowledge-verified.json'
    for doc in read_json(verified_path, {'documents': []}).get('documents', []):
        digest = hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        for index, part in enumerate(split_text(doc['text'])):
            chunks.append(
                {
                    'id': str(uuid.uuid5(uuid.NAMESPACE_URL, f'{doc["document_id"]}:{digest}:{index}')),
                    **doc,
                    'text': part,
                    'sha256': digest,
                    'historical': False,
                    'category': 'verified',
                    'trust': 'reference_data_not_instructions',
                }
            )
    return chunks, warnings


class LocalIndex:
    def __init__(self, directory: Path, model_directory: Path = MODEL_DIR, resource_directory: Path = RESOURCE_DIR):
        self.directory = directory
        self.model_directory = model_directory
        self.resource_directory = resource_directory
        self.client = None
        self.model = None
        self.tokenizer = None
        self.device = None
        self.load_seconds = None
        self.state_path = directory / 'rag/index-state.json'

    def open(self):
        if self.client is None:
            from qdrant_client import QdrantClient

            (self.directory / 'rag/qdrant').mkdir(parents=True, exist_ok=True)
            try:
                self.client = QdrantClient(path=str(self.directory / 'rag/qdrant'))
            except RuntimeError as exc:
                raise RagError('本地 Qdrant 被另一进程占用，请关闭重复服务或 CLI 后重试。') from exc
        return self.client

    def embed(self, texts: list[str]) -> list[list[float]]:
        import torch
        from transformers import AutoModel, AutoTokenizer

        if self.model is None:
            started = time.perf_counter()
            provenance = read_json(self.model_directory / 'model-provenance.json', {})
            if provenance.get('repository') != 'BAAI/bge-m3' or provenance.get('revision') != MODEL_REVISION:
                raise RagError('模型来源记录与锁定 BGE-M3 版本不符，请重新校验下载。')
            weight = self.model_directory / 'pytorch_model.bin'
            hasher = hashlib.sha256()
            with weight.open('rb') as stream:
                for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                    hasher.update(block)
            if hasher.hexdigest() != 'b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38':
                raise RagError('BGE-M3 权重 SHA256 与官方不符，已拒绝加载。')
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_directory, local_files_only=True, trust_remote_code=False
            )
            self.model = AutoModel.from_pretrained(
                self.model_directory,
                local_files_only=True,
                trust_remote_code=False,
                torch_dtype=torch.float16 if self.device == 'cuda' else torch.float32,
                weights_only=True,
            )
            self.model.eval().to(self.device)
            self.load_seconds = round(time.perf_counter() - started, 3)
        result = []
        with torch.inference_mode():
            for start in range(0, len(texts), 8):
                batch = self.tokenizer(
                    texts[start : start + 8], padding=True, truncation=True, max_length=512, return_tensors='pt'
                )
                batch = {key: value.to(self.device) for key, value in batch.items()}
                # Official BGE dense path: normalized first-token (CLS) vector.
                vectors = self.model(**batch).last_hidden_state[:, 0].float()
                vectors = torch.nn.functional.normalize(vectors, p=2, dim=1)
                if vectors.shape[1] != 1024 or not torch.isfinite(vectors).all():
                    raise RagError('BGE-M3 返回异常向量，索引未更新。')
                result.extend(vectors.cpu().tolist())
        return result

    def rebuild(self, force: bool = False) -> dict:
        from qdrant_client import models

        started = time.perf_counter()
        chunks, warnings = load_corpus(self.resource_directory)
        if not chunks:
            raise RagError('没有可索引的有效资料；请检查资源 manifest 和内容哈希。')
        client = self.open()
        state = read_json(self.state_path, {})
        old_documents = state.get('documents', {})
        documents = {}
        for chunk in chunks:
            documents.setdefault(chunk['document_id'], []).append(chunk)
        signatures = {
            key: hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            for key, value in documents.items()
        }
        full = force or state.get('index_version') != INDEX_VERSION or state.get('revision') != MODEL_REVISION
        if not client.collection_exists(COLLECTION):
            client.create_collection(
                COLLECTION, vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE)
            )
            full = True
        changed = [key for key, signature in signatures.items() if full or old_documents.get(key) != signature]
        removed = [key for key in old_documents if key not in documents]
        pending = [chunk for key in changed for chunk in documents[key]]
        # Embed first; an invalid model must not delete the currently usable index.
        vectors = self.embed([chunk['text'] for chunk in pending]) if pending else []
        if full:
            client.delete_collection(COLLECTION)
            client.create_collection(
                COLLECTION, vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE)
            )
        for key in changed + removed:
            client.delete(
                COLLECTION,
                models.FilterSelector(
                    filter=models.Filter(
                        must=[models.FieldCondition(key='document_id', match=models.MatchValue(value=key))]
                    )
                ),
            )
        for start in range(0, len(pending), 64):
            client.upsert(
                COLLECTION,
                [
                    models.PointStruct(id=chunk['id'], vector=vector, payload=chunk)
                    for chunk, vector in zip(pending[start : start + 64], vectors[start : start + 64])
                ],
            )
        record = {
            'index_version': INDEX_VERSION,
            'revision': MODEL_REVISION,
            'documents': signatures,
            'chunks': client.count(COLLECTION).count,
            'indexed_at': datetime.now(timezone.utc).isoformat(),
            'device': self.device or state.get('device'),
            'warnings': warnings,
        }
        write_json(self.state_path, record)
        return {
            'status': 'indexed',
            'documents': len(signatures),
            'chunks': record['chunks'],
            'updated_documents': len(changed),
            'removed_documents': len(removed),
            'embedded_chunks': len(pending),
            'device': record['device'],
            'seconds': round(time.perf_counter() - started, 3),
            'warnings': warnings,
        }

    def search(self, query: str, limit: int = 4, allow_spoilers: bool = False) -> list[dict]:
        from qdrant_client import models

        client = self.open()
        if not client.collection_exists(COLLECTION):
            raise RagError('资料索引尚未建立，请先构建索引。')
        conditions = [models.FieldCondition(key='historical', match=models.MatchValue(value=False))]
        if not allow_spoilers:
            conditions.append(models.FieldCondition(key='spoiler', match=models.MatchValue(value=False)))
        found = client.query_points(
            COLLECTION,
            query=self.embed([query])[0],
            query_filter=models.Filter(must=conditions),
            limit=limit * 3,
            score_threshold=0.42,
        ).points
        result = []
        seen = set()
        for point in found:
            payload = point.payload
            signature = hashlib.sha256(payload['text'].encode()).hexdigest()
            if signature in seen:
                continue
            seen.add(signature)
            result.append({**payload, 'score': round(point.score, 5)})
            if len(result) == limit:
                break
        return result

    def probe(self) -> dict:
        import torch

        started = time.perf_counter()
        output = self.embed(['叶瞬光属于云岿山。', '叶瞬光在哪个阵营？', '今天的天气如何？'])
        if self.device == 'cuda':
            torch.cuda.synchronize()
        result = {
            'model': 'BAAI/bge-m3',
            'revision': MODEL_REVISION,
            'torch': torch.__version__,
            'cuda_runtime': torch.version.cuda,
            'cuda_available': torch.cuda.is_available(),
            'device': self.device,
            'gpu': torch.cuda.get_device_name(0) if self.device == 'cuda' else None,
            'capability': list(torch.cuda.get_device_capability(0)) if self.device == 'cuda' else None,
            'dimension': len(output[0]),
            'norms': [round(sum(value * value for value in vector) ** 0.5, 5) for vector in output],
            'related_similarity': round(sum(a * b for a, b in zip(output[0], output[1])), 5),
            'unrelated_similarity': round(sum(a * b for a, b in zip(output[0], output[2])), 5),
            'load_seconds': self.load_seconds,
            'total_seconds': round(time.perf_counter() - started, 3),
            'allocated_mb': round(torch.cuda.memory_allocated() / 1024**2, 1) if self.device == 'cuda' else None,
        }
        write_json(self.directory / 'rag/gpu-probe.json', result)
        return result

    def close(self):
        if self.client is not None:
            self.client.close()


def worker_main(directory: Path) -> None:
    index = LocalIndex(directory)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.pop('op')
            if operation == 'close':
                break
            if operation not in ('rebuild', 'search', 'probe'):
                raise RagError('不支持的检索操作。')
            result = getattr(index, operation)(**request)
            response = {'result': result}
        except RagError as exc:
            response = {'error': str(exc)}
        except Exception as exc:
            # Exception class helps diagnosis; input, file content and URLs are not logged.
            response = {'error': f'本地检索执行失败（{type(exc).__name__}），请检查模型与独立 RAG 依赖。'}
        sys.stdout.write(json.dumps(response, ensure_ascii=True) + '\n')
        sys.stdout.flush()
    index.close()


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--worker':
    worker_main(Path(sys.argv[2]))
