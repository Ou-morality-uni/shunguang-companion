"""Download the official, pinned BGE-M3 dense model; never execute remote code."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
REPOSITORY = 'BAAI/bge-m3'
FILES = {
    'pytorch_model.bin': (2271145830, 'b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38'),
    'sentencepiece.bpe.model': (5069051, 'cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865'),
    'tokenizer.json': (17098108, '21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08'),
    'config.json': (687, '26159e7ad065073448460117eb24b7a4572f6f4e78eadff65dc0a11c052449fa'),
    'special_tokens_map.json': (964, '8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835'),
    'tokenizer_config.json': (444, 'a62b2b6784f990259fddef5f16388693a8043be4f69179e6a5257eeb3f9abac4'),
    '1_Pooling/config.json': (191, 'e54c164a07274f2eb45bb724f54a79d1efcc90c41573887cd9a29aeee0597352'),
    'modules.json': (349, '84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf'),
}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def valid(path: Path, size: int, expected: str | None) -> bool:
    return path.is_file() and path.stat().st_size == size and (expected is None or digest(path) == expected)


def download(destination: Path, supplied: Path | None = None, check_only: bool = False) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    old_path = destination / 'model-provenance.json'
    previous = json.loads(old_path.read_text(encoding='utf-8')) if old_path.exists() else {}
    origins = {item['filename']: item.get('origin') for item in previous.get('files', [])}
    records = []
    started = time.perf_counter()
    for name, (size, expected) in FILES.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        origin = origins.get(name) or 'existing_verified_file'
        if not valid(path, size, expected):
            if check_only:
                raise RuntimeError(f'Missing or invalid model component: {name}')
            if name == 'pytorch_model.bin' and supplied is not None:
                if not valid(supplied, size, expected):
                    raise RuntimeError('Supplied weight does not match the official pinned LFS SHA256')
                shutil.copy2(supplied, path)
                origin = 'user_supplied_sha256_matched'
            else:
                url = f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}?download=true'
                partial = path.with_suffix(path.suffix + '.partial')
                offset = partial.stat().st_size if partial.exists() else 0
                request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
                with urllib.request.urlopen(request, timeout=120) as response:
                    append = offset > 0 and response.status == 206
                    if not append:
                        offset = 0
                    next_notice = offset + 256 * 1024 * 1024
                    with partial.open('ab' if append else 'wb') as output:
                        while block := response.read(4 * 1024 * 1024):
                            output.write(block)
                            offset += len(block)
                            if offset >= next_notice:
                                print(f'{name}: {offset}/{size} bytes', flush=True)
                                next_notice += 256 * 1024 * 1024
                if not valid(partial, size, expected):
                    raise RuntimeError(f'Download hash/size mismatch: {name}; partial retained for inspection')
                partial.replace(path)
                origin = 'official_pinned_download'
        records.append({'filename': name, 'bytes': size, 'sha256': digest(path), 'origin': origin})
        print(f'{name}: verified', flush=True)
    result = {'repository': REPOSITORY, 'revision': REVISION, 'license': 'MIT', 'format': 'PyTorch state_dict',
              'source': f'https://huggingface.co/{REPOSITORY}/tree/{REVISION}', 'files': records,
              'seconds': round(time.perf_counter() - started, 3)}
    (destination / 'model-provenance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, default=ROOT / 'source/resources/models/bge-m3')
    parser.add_argument('--supplied-weight', type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(download(args.destination, args.supplied_weight, args.check_only), ensure_ascii=True, indent=2))
