"""Download the official, pinned BGE-M3 dense model; never execute remote code."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import urllib.request
import urllib.error
import zipfile
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


def fetch_asset(record: dict, cache: Path) -> Path:
    """Resume a public HTTPS asset and reject a wrong length or digest."""
    name = record['name']
    if Path(name).name != name or not record['url'].startswith('https://'):
        raise RuntimeError('Invalid model asset name or URL')
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / name
    if valid(target, record['bytes'], record['sha256']):
        print(f'{name}: cached and verified', flush=True)
        return target
    partial = cache / (name + '.partial')
    if valid(partial, record['bytes'], record['sha256']):
        partial.replace(target)
        return target
    for attempt in range(3):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset >= record['bytes']:
            raise RuntimeError(f'Invalid cached asset: {partial.name}; remove that cache file and retry')
        request = urllib.request.Request(record['url'], headers={
            'User-Agent': 'Shunguang-Installer/0.2',
            **({'Range': f'bytes={offset}-'} if offset else {})})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                append = offset > 0 and response.status == 206
                if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                    raise RuntimeError('Server returned an invalid resume range')
                if not append:
                    offset = 0
                next_notice = offset + 64 * 1024 * 1024
                with partial.open('ab' if append else 'wb') as stream:
                    while block := response.read(4 * 1024 * 1024):
                        stream.write(block)
                        offset += len(block)
                        if offset > record['bytes']:
                            raise RuntimeError('Model download exceeded its declared size')
                        if offset >= next_notice:
                            print(f'{name}: {offset}/{record["bytes"]} bytes', flush=True)
                            next_notice += 64 * 1024 * 1024
            if not valid(partial, record['bytes'], record['sha256']):
                raise RuntimeError(f'Asset hash/size mismatch: {name}; cache retained for inspection')
            partial.replace(target)
            return target
        except (OSError, urllib.error.URLError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f'Model release download failed: HTTP {exc.code}') from exc
            if attempt == 2:
                raise RuntimeError('Model download failed after 3 attempts; run Install.bat again to resume') from exc
            print('Download interrupted; retrying the retained partial file.', flush=True)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError('Model asset download did not complete')


def extract_release(archive: Path, manifest: dict, destination: Path) -> None:
    """Only extract the declared model files; never accept arbitrary ZIP paths."""
    expected = {'bge-m3/' + item['path']: item for item in manifest['files']}
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise RuntimeError('Model ZIP entries differ from the pinned manifest')
        for name in names:
            record = expected[name]
            relative = Path(record['path'])
            path = (destination / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(destination.resolve()):
                raise RuntimeError('Unsafe model ZIP path')
            info = package.getinfo(name)
            if info.file_size != record['bytes'] or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError('Invalid model ZIP member')
            if valid(path, record['bytes'], record['sha256']):
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.installing')
            with package.open(info) as source, temporary.open('wb') as output:
                shutil.copyfileobj(source, output, length=4 * 1024 * 1024)
            if not valid(temporary, record['bytes'], record['sha256']):
                raise RuntimeError('Extracted model file failed SHA256 verification')
            temporary.replace(path)
            print(f'{record["path"]}: extracted and verified', flush=True)


def download_release(destination: Path, manifest_path: Path, cache: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('repository') != REPOSITORY or manifest.get('revision') != REVISION:
        raise RuntimeError('Model release identity does not match the pinned upstream revision')
    components = {entry['path']: entry for entry in manifest['files']}
    for name, (size, expected) in FILES.items():
        if components.get(name, {}).get('bytes') != size or components[name].get('sha256') != expected:
            raise RuntimeError('Model release component differs from the official SHA256')
    reused = all(valid(destination / name, size, expected) for name, (size, expected) in FILES.items())
    if not reused:
        paths = [fetch_asset(asset, cache) for asset in manifest['assets']]
        archive_record = manifest['archive']
        if len(paths) == 1 and paths[0].name == archive_record['name']:
            archive = paths[0]
        else:
            archive = cache / archive_record['name']
            if not valid(archive, archive_record['bytes'], archive_record['sha256']):
                temporary = archive.with_suffix('.joining')
                with temporary.open('wb') as output:
                    for path in paths:
                        with path.open('rb') as source:
                            shutil.copyfileobj(source, output, length=4 * 1024 * 1024)
                if not valid(temporary, archive_record['bytes'], archive_record['sha256']):
                    raise RuntimeError('Combined model archive failed verification')
                temporary.replace(archive)
        if not valid(archive, archive_record['bytes'], archive_record['sha256']):
            raise RuntimeError('Model archive failed verification')
        extract_release(archive, manifest, destination)
    result = download(destination, check_only=True)
    result['distribution'] = {'type': 'existing_verified_components' if reused else 'github_release',
                              'release_url': manifest['release_url'], 'assets': manifest['assets'],
                              'archive_sha256': manifest['archive']['sha256']}
    (destination / 'model-provenance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, default=ROOT / 'source/resources/models/bge-m3')
    parser.add_argument('--supplied-weight', type=Path)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--source', choices=('release', 'official'), default='release')
    parser.add_argument('--release-manifest', type=Path, default=ROOT / 'source/resources/verified/bge-m3-release.json')
    parser.add_argument('--cache', type=Path, default=ROOT / 'data/install/model-cache')
    args = parser.parse_args()
    if args.check_only or args.supplied_weight or args.source == 'official':
        result = download(args.destination, args.supplied_weight, args.check_only)
    else:
        result = download_release(args.destination, args.release_manifest, args.cache)
    print(json.dumps(result, ensure_ascii=True, indent=2))
