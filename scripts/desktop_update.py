"""Windows foreground update supervisor. All transaction files stay on the project volume."""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path, PureWindowsPath
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
STATE = '.shunguang-update'
LIST = 'scripts/update-managed.txt'
VERSION_RE = r'(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2}'
MAX_BYTES = 2_000_000_000
ROOT_FILES = {
    'README.md',
    'README.en.md',
    'pyproject.toml',
    'update.json',
    'Start_up.bat',
    'Install.bat',
    'INSTALL_LIST.md',
}
DIRS = {'backend', 'scripts', 'frontend', 'source', 'skills', 'versions', 'docs', 'deploy'}


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, value):
    tmp = path.with_suffix('.' + uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked(root, name):
    parts = name.split('/')
    if (
        parts[0] not in DIRS
        and name not in ROOT_FILES
        or any(
            not part
            or part in ('.', '..')
            or part.endswith((' ', '.'))
            or re.search(r'[\\:\x00-\x1f<>|"?*]', part)
            or PureWindowsPath(part).is_reserved()
            or part.lower() in ('.git', 'node_modules', '__pycache__')
            for part in parts
        )
    ):
        raise ValueError('更新包含无效文件名。')
    p = root
    for part in parts:
        p = p / part
        if p.is_symlink() or (
            p.exists() and getattr(p.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError('更新路径含有链接：' + name)
    return p


def baseline(root):
    names = (root / LIST).read_text(encoding='utf-8-sig').splitlines()
    names += [p.relative_to(root).as_posix() for p in (root / 'frontend/dist').rglob('*') if p.is_file()]
    return {name: sha(checked(root, name)) for name in names}


def record_baseline(root):
    state = root / STATE
    state.mkdir(exist_ok=True)
    write_json(state / 'baseline.json', baseline(root))
    (state / 'python.txt').write_text(sys._base_executable, encoding='utf-8')
    replace_file(root / 'scripts/desktop_update.py', state / 'supervisor.py')


def build(root, output):
    files = baseline(root)
    version = read_json(root / 'update.json')['version']
    if not re.fullmatch(VERSION_RE, version):
        raise ValueError('版本无效')
    page = root / 'frontend/dist/index.html'
    if not page.is_file() or f'name="shunguang-version" content="{version}"' not in page.read_text(encoding='utf-8'):
        raise ValueError('请先构建与发布版本一致的网页')
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps({'version': version, 'files': files}))
        for name in files:
            archive.write(root / name, name)


def submit_request(root, version, digest, size):
    state = root / STATE
    job = uuid4().hex
    tmp = state / (job + '.request')
    write_json(tmp, dict(id=job, version=version, digest=digest, size=size))
    try:
        os.link(tmp, state / 'request.json')  # Publish complete request, reject concurrent submissions.
    finally:
        tmp.unlink(missing_ok=True)
    return job


def download(job, target):
    version = job['version']
    if not re.fullmatch(VERSION_RE, version) or not 0 < job['size'] <= MAX_BYTES:
        raise ValueError('无效的更新版本或大小')
    url = f'https://github.com/Ou-morality-uni/shunguang-companion/releases/download/v{version}/shunguang-{version}-windows.zip'
    count = 0
    with (
        urlopen(Request(url, headers={'User-Agent': 'Shunguang-Updater'}), timeout=45) as response,
        target.open('xb') as f,
    ):
        if not response.url.startswith('https://'):
            raise ValueError('更新包下载地址无效')
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > job['size']:
                raise ValueError('更新包大小不符')
            f.write(chunk)
    if count != job['size'] or sha(target) != job['digest']:
        raise ValueError('更新包完整性校验失败')


def unpack(package, stage, version):
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 20000
            or sum(i.file_size for i in entries) > 4 * MAX_BYTES
            or archive.getinfo('manifest.json').file_size > 4_000_000
            or len({i.filename.casefold() for i in entries}) != len(entries)
        ):
            raise ValueError('更新包目录无效')
        manifest = json.loads(archive.read('manifest.json'))
        files = manifest['files']
        if (
            manifest['version'] != version
            or set(archive.namelist()) != set(files) | {'manifest.json'}
            or not {LIST, 'update.json', 'frontend/dist/index.html', 'backend/requirements.lock.txt'} <= files.keys()
        ):
            raise ValueError('更新清单不匹配')
        for name, digest in files.items():
            path = checked(stage, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, path.open('xb') as dest:
                shutil.copyfileobj(src, dest)
            if sha(path) != digest:
                raise ValueError('更新文件校验失败：' + name)
        if read_json(stage / 'update.json')['version'] != version:
            raise ValueError('程序版本与发布版本不一致')
        return files


def changes(root, old, new):
    changed = []
    for name in sorted(old.keys() | new.keys()):
        path = checked(root, name)
        actual = sha(path) if path.is_file() else None
        if actual != old.get(name) and actual != new.get(name):
            raise ValueError('发现本地文件改动：' + name)
        if actual != new.get(name):
            changed.append(name)
    return changed


def prepare(root, txn, job):
    if shutil.disk_usage(root).free < 3 * job['size']:
        raise ValueError('磁盘空间不足')
    package = txn / 'package.zip'
    download(job, package)
    new = unpack(package, txn / 'stage', job['version'])
    old = read_json(root / STATE / 'baseline.json')
    changed = changes(root, old, new)
    if 'backend/requirements.lock.txt' in changed:
        subprocess.run(
            [
                sys.executable,
                '-m',
                'pip',
                'download',
                '--only-binary=:all:',
                '--dest',
                str(txn / 'wheels'),
                '-r',
                str(txn / 'stage/backend/requirements.lock.txt'),
            ],
            check=True,
        )
    write_json(txn / 'target.json', new)


def progress(root, job, phase, message):
    write_json(root / STATE / 'status.json', dict(id=job['id'], version=job['version'], phase=phase, message=message))


def snapshot(root, txn):
    old = read_json(root / STATE / 'baseline.json')
    new = read_json(txn / 'target.json')
    names = changes(root, old, new)
    data = root / 'data'

    # The launcher and installer own open lock files; they contain no application state.
    def ignored(directory, entries):
        for name in entries:
            p = Path(directory) / name
            if p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('数据备份遇到链接：' + name)
        return {n for n in entries if Path(directory) == data / 'install' and n.endswith('.lock')}

    if data.resolve() != data.absolute():
        raise ValueError('数据目录含有链接')
    needed = sum(p.stat().st_size for p in data.rglob('*') if p.is_file())
    needed += sum((root / n).stat().st_size for n in names if (root / n).is_file())
    if shutil.disk_usage(root).free < needed + 100 * 1024 * 1024:
        raise ValueError('备份空间不足')
    shutil.copytree(data, txn / 'data-backup', ignore=ignored)
    for name in names:
        path = checked(root, name)
        if path.is_file():
            saved = txn / 'original' / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
    write_json(txn / 'undo.json', dict(names=names, baseline=old))
    return names


def replace_file(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + '.' + uuid4().hex + '.tmp')
    try:
        shutil.copy2(src, temp)
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)


def activate(root, txn, names):
    for name in names:
        dest = checked(root, name)
        src = txn / 'stage' / name
        if src.exists():
            replace_file(src, dest)
        else:
            dest.unlink(missing_ok=True)
    if (txn / 'wheels').exists():
        (root / '.venv').rename(txn / 'previous-env')
        subprocess.run([sys.executable, '-m', 'venv', str(root / '.venv')], check=True)
        subprocess.run(
            [
                str(root / '.venv/Scripts/python.exe'),
                '-m',
                'pip',
                'install',
                '--no-index',
                '--find-links',
                str(txn / 'wheels'),
                '-r',
                str(root / 'backend/requirements.lock.txt'),
            ],
            check=True,
        )
    fingerprint = subprocess.check_output(
        [
            'powershell.exe',
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-Command',
            '. ./scripts/prepare-launch.ps1; Get-InstallFingerprint',
        ],
        cwd=root,
        text=True,
    ).strip()
    if not re.fullmatch('[0-9a-f]{64}', fingerprint):
        raise ValueError('无法校验安装输入')
    prefs = root / 'data/install/preferences.json'
    write_json(prefs, read_json(prefs) | {'fingerprint': fingerprint})
    write_json(root / STATE / 'baseline.json', read_json(txn / 'target.json'))


def restore(root, txn):
    undo = read_json(txn / 'undo.json')
    for name in undo['names']:
        dest = checked(root, name)
        saved = txn / 'original' / name
        if saved.is_file():
            replace_file(saved, dest)
        else:
            dest.unlink(missing_ok=True)
    if (txn / 'previous-env').exists():
        if (root / '.venv').exists():
            (root / '.venv').rename(txn / ('failed-env-' + uuid4().hex))
        (txn / 'previous-env').rename(root / '.venv')
    data = root / 'data'
    backup = txn / 'data-backup'
    # Isolate files created by a failed migration before restoring original data.
    for directory, _, names in os.walk(data, followlinks=False):
        for name in names:
            live = Path(directory) / name
            relative = live.relative_to(data)
            if relative.parent == Path('install') and name.endswith('.lock'):
                continue
            if not (backup / relative).exists():
                extra = txn / 'failed-data' / relative
                extra.parent.mkdir(parents=True, exist_ok=True)
                os.replace(live, extra)
    for db in (txn / 'data-backup').rglob('*.sqlite3'):
        dest = root / 'data' / db.relative_to(txn / 'data-backup')
        for suffix in ('-wal', '-shm', '-journal'):
            Path(str(dest) + suffix).unlink(missing_ok=True)
    shutil.copytree(txn / 'data-backup', root / 'data', dirs_exist_ok=True)
    write_json(root / STATE / 'baseline.json', undo['baseline'])


def launch(root, port):
    return subprocess.Popen(
        [str(root / '.venv/Scripts/python.exe'), '-u', str(root / 'scripts/run-console.py'), '--port', str(port)],
        cwd=root,
        env=os.environ | {'SHUNGUANG_UPDATE_SUPERVISED': '1'},
    )


def healthy(child, port, version):
    until = time.monotonic() + 60
    while child.poll() is None and time.monotonic() < until:
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2) as r:
                info = json.load(r)
            with urlopen(f'http://127.0.0.1:{port}/', timeout=2) as r:
                page = r.read(256000).decode()
            if (
                info.get('version') == version
                and info.get('dependencies', {}).get('storage') == 'ready'
                and f'name="shunguang-version" content="{version}"' in page
            ):
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.4)
    return False


def transaction_dir(root, job):
    state = root.resolve() / STATE
    if not re.fullmatch('[0-9a-f]{32}', job['id']) or state.resolve() != state:
        raise ValueError('更新事务目录无效')
    txn = state / job['id']
    if txn.resolve() != txn:
        raise ValueError('更新事务目录含有链接')
    return txn


def supervise(root, port):
    state = root / STATE
    state.mkdir(exist_ok=True)
    request = state / 'request.json'
    journal = state / 'switch.json'
    if journal.is_file():
        job = read_json(journal)
        restore(root, transaction_dir(root, job))
        journal.unlink()
        progress(root, job, 'failed', '中断的更新已恢复至原版本。')
    if request.exists():
        progress(root, read_json(request), 'failed', '上次更新已中断，可重新检查。')
        request.unlink()
    child = launch(root, port)
    try:
        while child.poll() is None:
            if not request.exists():
                time.sleep(0.4)
                continue
            job = read_json(request)
            txn = transaction_dir(root, job)
            txn.mkdir()
            try:
                progress(root, job, 'preparing', '正在下载、校验更新包并准备依赖。')
                prepare(root, txn, job)
                if child.poll() is not None:
                    raise ValueError('原服务已退出')
                progress(root, job, 'draining', '等待当前任务结束并重启服务。')
                if child.wait() != 75:
                    raise ValueError('服务退出，更新已取消')
                names = snapshot(root, txn)
                write_json(journal, job)
                progress(root, job, 'switching', '正在切换版本，保留此页面。')
                activate(root, txn, names)
                child = launch(root, port)
                if not healthy(child, port, job['version']):
                    raise ValueError('新版启动验证失败')
                replace_file(root / 'scripts/desktop_update.py', state / 'supervisor.py')
                journal.unlink()
                progress(root, job, 'complete', '更新完成。')
            except Exception as error:
                if journal.exists():
                    if child.poll() is None:
                        child.terminate()
                        child.wait()
                    restore(root, txn)
                    journal.unlink()
                progress(root, job, 'failed', '更新未完成：' + str(error)[:240])
                if child.poll() is not None:
                    child = launch(root, port)
            finally:
                request.unlink(missing_ok=True)
                if not journal.exists():
                    shutil.rmtree(txn, ignore_errors=True)
        return child.returncode
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('baseline', 'build', 'supervise'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.command == 'baseline':
        record_baseline(ROOT)
    elif args.command == 'build':
        build(ROOT, args.output)
    else:
        sys.exit(supervise(ROOT, args.port))
