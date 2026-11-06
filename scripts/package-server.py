"""Build a private-data-free Linux server archive from explicit source roots."""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.constants import VERSION


def files():
    for path in (ROOT / 'backend').rglob('*.py'):
        if 'tests' not in path.relative_to(ROOT / 'backend').parts and '__pycache__' not in path.parts:
            yield path
    yield ROOT / 'backend/requirements.lock.txt'
    yield from (ROOT / 'backend/prompts').glob('*.md')
    for path in (ROOT / 'frontend/dist').rglob('*'):
        if path.is_file():
            yield path
    for directory in (
        'source/resources/character/stickers',
        'source/resources/assets/ye-shunguang',
        'source/resources/fonts',
        'skills',
    ):
        for path in (ROOT / directory).rglob('*'):
            if (
                path.is_file()
                and '__pycache__' not in path.parts
                and path.suffix.lower()
                in (
                    '.py',
                    '.md',
                    '.txt',
                    '.json',
                    '.js',
                    '.css',
                    '.html',
                    '.wasm',
                    '.gz',
                    '.png',
                    '.jpg',
                    '.webp',
                    '.svg',
                    '.ico',
                    '.ttf',
                    '.woff',
                    '.woff2',
                    '.bin',
                )
            ):
                yield path
    yield ROOT / 'source/resources/character/avatar.png'
    for name in ('reference-original.mp3', 'reference-original-30s-50s.mp3'):
        yield ROOT / 'source/resources/voice/ye-shunguang' / name


def package(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise RuntimeError('先运行 npm --prefix frontend run build')
    build = VERSION + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    with tempfile.TemporaryDirectory(prefix='server-package-', dir=destination) as temporary:
        staging = Path(temporary) / 'ye-shunguang-server-lite'
        staging.mkdir()
        for source in sorted(set(files())):
            if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
                raise ValueError('打包源包含链接或越界路径')
            target = staging / 'app' / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for source in (ROOT / 'deploy/server-lite').iterdir():
            if source.is_file() and not source.is_symlink():
                shutil.copyfile(source, staging / source.name)
        guide = ROOT / 'docs/server-deployment.md'
        if not guide.is_file():
            raise RuntimeError('缺少公开服务器部署指南：docs/server-deployment.md')
        (staging / 'README-服务器部署.md').write_text(
            guide.read_text(encoding='utf-8').replace('(qq-setup.md)', '(docs/qq-setup.md)'), encoding='utf-8'
        )
        notes = (ROOT / f'versions/{VERSION}/README.md').read_text(encoding='utf-8')
        (staging / 'VERSION-NOTES.md').write_text(
            notes.replace('(../0.7.1/README.md)', '(docs/version-0.7.1.md)').replace('(../../docs/', '(docs/'),
            encoding='utf-8',
        )
        (staging / 'docs').mkdir()
        shutil.copyfile(ROOT / 'versions/0.7.1/README.md', staging / 'docs/version-0.7.1.md')
        for guide in ('qq-setup.md', 'server-deployment.md'):
            shutil.copyfile(ROOT / 'docs' / guide, staging / 'docs' / guide)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        if '## 许可与使用范围' not in readme:
            raise RuntimeError('缺少项目许可声明，不生成不完整分发包')
        (staging / 'LICENSE-NOTICE.md').write_text(
            '# 许可与使用范围\n' + readme.split('## 许可与使用范围', 1)[1], encoding='utf-8'
        )
        for filename in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
            if (ROOT / filename).is_file():
                shutil.copyfile(ROOT / filename, staging / filename)
        (staging / 'app/server-build.json').write_text(json.dumps({'build': build}), encoding='utf-8')
        manifest = {'format': 1, 'version': VERSION, 'build': build, 'platform': 'linux/amd64', 'files': {}}
        for path in sorted(staging.rglob('*')):
            if path.is_file():
                # Shell scripts are always LF, including archives made on Windows.
                if path.suffix in ('.sh', '.py', '.yaml') or path.name in ('Dockerfile', '.dockerignore'):
                    path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
                manifest['files'][path.relative_to(staging).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        (staging / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        archive_path = destination / f'ye-shunguang-server-lite-{VERSION}-linux.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(staging.rglob('*')):
                if path.is_file():
                    archive.write(path, 'ye-shunguang-server-lite/' + path.relative_to(staging).as_posix())
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive_path.with_suffix('.zip.sha256').write_text(digest + '  ' + archive_path.name + '\n', encoding='utf-8')
        print(
            json.dumps(
                {
                    'archive': str(archive_path),
                    'sha256': digest,
                    'build': build,
                    'files': len(manifest['files']),
                    'bytes': archive_path.stat().st_size,
                },
                ensure_ascii=False,
            )
        )
        return archive_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / 'delivery'))
    package(parser.parse_args().output)
