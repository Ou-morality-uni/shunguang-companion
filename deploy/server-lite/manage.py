"""Linux deployment controller. Host Python uses only the standard library."""

import argparse
import base64
import getpass
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def run(args, *, cwd=ROOT, payload=None, capture=False):
    return subprocess.run(
        args,
        cwd=cwd,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        check=True,
        capture_output=capture,
    )


def verify(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1 or not re.fullmatch(r'[a-zA-Z0-9._-]+', manifest.get('build', '')):
        raise ValueError('部署包清单无效')
    if manifest.get('platform') != 'linux/amd64':
        raise ValueError('部署包平台不受支持')
    for name, expected in manifest['files'].items():
        path = directory / name
        if path.is_symlink() or not path.resolve().is_relative_to(directory) or not path.is_file():
            raise ValueError('部署包路径无效')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('部署包校验失败：' + name)
    return manifest


def unpack(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        if len(entries) > 10000 or sum(e.file_size for e in entries) > 1024**3:
            raise ValueError('部署包超过大小限制')
        seen = set()
        for entry in entries:
            name = PurePosixPath(entry.filename)
            if (
                '\\' in entry.filename
                or name.is_absolute()
                or '..' in name.parts
                or not name.parts
                or name.parts[0] != 'ye-shunguang-server-lite'
                or stat.S_ISLNK(entry.external_attr >> 16)
                or entry.filename in seen
            ):
                raise ValueError('归档包含越界路径、链接或重复文件')
            seen.add(entry.filename)
            target = destination.joinpath(*name.parts)
            if not target.resolve().is_relative_to(destination):
                raise ValueError('解压目标越界')
        for entry in entries:
            target = destination.joinpath(*PurePosixPath(entry.filename).parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(entry) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
    root = destination / 'ye-shunguang-server-lite'
    verify(root)
    return root


def environment(directory=ROOT):
    result = {}
    path = Path(directory) / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.startswith('#'):
                key, value = line.split('=', 1)
                result[key] = value
    return result


def private_file(path, data, *, owner=False):
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(data)
    if owner and os.name != 'nt' and os.geteuid() == 0:
        os.chown(path, 10001, 10001)


def write_env(directory, values):
    path = Path(directory) / '.env'
    text = ''.join(f'{key}={value}\n' for key, value in values.items())
    temporary = path.with_name('.env.' + stamp())
    private_file(temporary, text.encode())
    os.replace(temporary, path)


def compose(directory, *args, payload=None, capture=False):
    values = environment(directory)
    legacy_qq = 'COMPOSE_PROFILES' not in values and (Path(values.get('RUNTIME_DIR', '.')) / 'napcat.env').is_file()
    profiles = ['--profile', 'qq'] if legacy_qq else []
    return run(
        [
            'docker',
            'compose',
            '--env-file',
            str(Path(directory) / '.env'),
            '-f',
            str(Path(directory) / 'compose.yaml'),
            *profiles,
            *args,
        ],
        cwd=directory,
        payload=payload,
        capture=capture,
    )


def preflight():
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
        raise ValueError('本部署包需要 Linux x86_64。请先核对系统，不要重装已有服务器。')
    if os.geteuid() != 0:
        raise ValueError('请通过 sudo 运行此脚本，以设置数据及主密钥的权限。')
    if not shutil.which('docker'):
        raise ValueError('尚未安装 Docker。请按手册安装 Docker Engine 和 Compose 后重试。')
    result = run(['docker', 'version', '--format', '{{.Server.Version}}'], capture=True)
    version = result.stdout.strip().split('.')
    if not version or not version[0].isdigit() or int(version[0]) < 28:
        raise ValueError('需要 Docker Engine 28 或更新版本，确认 loopback 端口发布行为。')
    run(['docker', 'compose', 'version'], capture=True)
    if any(char.isspace() or char in '$#"\'' for char in str(ROOT)):
        raise ValueError('请将部署包解压到不含空格和特殊字符的目录，例如 /opt/shunguang。')


def runtime_path():
    value = Path(environment().get('RUNTIME_DIR', str(ROOT / 'runtime')))
    if not value.is_absolute() or value.is_symlink() or not value.is_dir():
        raise ValueError('持久化目录无效，请检查原安装目录的 .env')
    return value.resolve()


def initialize(with_qq=False, pip_source=None):
    manifest = verify(ROOT)
    preflight()
    if not (ROOT / '.env').exists():
        existing = run(
            [
                'docker',
                'ps',
                '-a',
                '--filter',
                'label=com.docker.compose.project=shunguang-server-lite',
                '--format',
                '{{.ID}}',
            ],
            capture=True,
        )
        if existing.stdout.strip():
            raise ValueError('已有叶瞬光 Compose 实例。请回原安装目录更新或恢复，不新建覆盖。')
        for port in (8000, 3001, 6099) if with_qq else (8000,):
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', port))
                except OSError:
                    raise ValueError(f'端口 {port} 已被使用，请先检查既有服务，脚本不会停止它。') from None
        root = ROOT / 'runtime'
        if root.exists():
            raise ValueError('检测到未登记的 runtime 目录。请按手册恢复，不自动覆盖。')
        for relative in ('data', 'secrets', 'backups', 'napcat/qq', 'napcat/config', 'napcat/plugins'):
            path = root / relative
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
            os.chown(path, 10001, 10001)
        root.chmod(0o700)
        private_file(root / 'secrets/master.key', base64.urlsafe_b64encode(secrets.token_bytes(32)), owner=True)
        token = secrets.token_urlsafe(32)
        webui = secrets.token_urlsafe(24)
        config = {
            'network': {
                'httpServers': [],
                'httpClients': [],
                'websocketClients': [],
                'websocketServers': [
                    {
                        'name': 'shunguang',
                        'enable': True,
                        'host': '0.0.0.0',
                        'port': 3001,
                        'messagePostFormat': 'array',
                        'enableForcePushEvent': True,
                        'debug': False,
                        'reportSelfMessage': False,
                        'token': token,
                        'heartInterval': 30000,
                    }
                ],
            },
            'musicSignUrl': '',
            'enableLocalFile2Url': False,
            'parseMultMsg': False,
        }
        private_file(root / 'napcat/config/onebot11.json', json.dumps(config).encode(), owner=True)
        private_file(root / 'napcat.env', f'WEBUI_TOKEN={webui}\n'.encode())
        write_env(
            ROOT,
            {
                'RUNTIME_DIR': str(root.resolve()),
                'RELEASES_DIR': str((ROOT.parent / 'shunguang-releases').resolve()),
                'SHUNGUANG_IMAGE': 'shunguang-server-lite:' + manifest['build'],
                'APP_MEMORY': '512m',
                'PIP_SOURCE': pip_source or 'official',
                'COMPOSE_PROFILES': 'qq' if with_qq else '',
                'NAPCAT_MEMORY': '1024m',
                'NAPCAT_IMAGE': 'mlikiowa/napcat-docker:v4.18.41@sha256:b101b8968cc31ae428ec0f8e117386e4ced7773b2d8226ed9f7ddfcec55f1b7e',
            },
        )
    if pip_source is not None:
        values = environment()
        values['PIP_SOURCE'] = pip_source
        write_env(ROOT, values)
    root = runtime_path()
    if not (root / 'secrets/master.key').is_file():
        raise ValueError('主密钥丢失，禁止重新生成。请从备份恢复。')
    compose(ROOT, 'config', '--quiet')
    compose(ROOT, 'build', 'app')
    if not (root / 'data/access.json').exists():
        payload = {}
        if environment().get('COMPOSE_PROFILES') == 'qq':
            account = input('机器人 QQ 号：').strip()
            if not re.fullmatch(r'\d{5,20}', account):
                raise ValueError('QQ 号格式无效')
            config = json.loads((root / 'napcat/config/onebot11.json').read_text())
            payload = {'bot_id': account, 'token': config['network']['websocketServers'][0]['token']}
        password = getpass.getpass('叶瞬光管理密码（至少 10 位）：')
        if len(password) < 10 or password != getpass.getpass('再次输入：'):
            raise ValueError('密码不足 10 位或两次不一致')
        compose(
            ROOT,
            'run',
            '--rm',
            '--no-deps',
            '-T',
            'app',
            'python',
            '-m',
            'backend.server_admin',
            'init',
            payload={'password': password, **payload},
        )
    compose(ROOT, 'up', '-d')
    wait_healthy(ROOT)
    print('应用已启动。QQ 登录和绑定请在面板完成；程序存活不代表 QQ 已在线。')
    print('在你的电脑建立隧道：ssh -N -L 18000:127.0.0.1:8000 -L 16099:127.0.0.1:6099 用户名@服务器IP')
    print('叶瞬光 http://127.0.0.1:18000/ ；NapCat http://127.0.0.1:16099/webui/')
    print('NapCat WebUI 密码保存在 runtime/napcat.env；请在服务器私下查看，不要发到聊天。')


def wait_healthy(directory):
    for _ in range(60):
        try:
            status = compose(directory, 'ps', '--format', 'json', 'app', capture=True).stdout.strip()
            # Compose versions emit a JSON object per line or an array.
            rows = json.loads(status) if status.startswith('[') else [json.loads(line) for line in status.splitlines()]
            if any(row.get('Health') == 'healthy' and row.get('State') == 'running' for row in rows):
                return
        except (ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(2)
    raise RuntimeError('应用未在 120 秒内健康。运行 doctor.sh 查看状态，勿反复重新初始化。')


def passphrase(confirm=False):
    password = getpass.getpass('备份加密口令（至少 12 位，丢失将无法恢复）：')
    if len(password) < 12 or (confirm and password != getpass.getpass('再次输入备份口令：')):
        raise ValueError('备份口令不足 12 位或不一致')
    return password


def backup(directory, password, *, full=False):
    values = environment(directory)
    root = Path(values['RUNTIME_DIR'])
    name = 'backup-' + stamp() + '.sgbackup'
    args = ['run', '--rm', '--no-deps', '-T']
    if full:
        args += ['--volume', str(root / 'napcat') + ':/napcat-backup:ro']
        args += ['--volume', str(root / 'napcat.env') + ':/napcat.env:ro']
    args += ['app', 'python', '-m', 'backend.server_admin', 'backup']
    compose(directory, *args, payload={'password': password, 'name': name, 'full': full})
    print('已生成加密备份：' + str(root / 'backups' / name))
    return name


def update(archive):
    preflight()
    verify(ROOT)
    values = environment()
    root = runtime_path()
    password = passphrase(confirm=True)
    release_parent = Path(values.get('RELEASES_DIR', str(ROOT.parent / 'shunguang-releases')))
    release_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='unpack-', dir=release_parent) as staging:
        source = unpack(archive, staging)
        manifest = verify(source)
        target = release_parent / manifest['build']
        if target.exists():
            if target.is_symlink() or verify(target)['files'] != manifest['files']:
                raise ValueError('同名构建内容不同，拒绝覆盖。请核对上传的包。')
            if environment(target).get('RUNTIME_DIR') not in (None, str(root)):
                raise ValueError('该构建目录属于另一份运行数据，拒绝覆盖。')
        else:
            shutil.move(str(source), target)
    new_values = dict(values, SHUNGUANG_IMAGE='shunguang-server-lite:' + manifest['build'])
    write_env(target, new_values)
    compose(target, 'config', '--quiet')
    compose(target, 'build', 'app')
    compose(ROOT, 'stop', 'app')
    try:
        name = backup(ROOT, password)
    except Exception:
        compose(ROOT, 'up', '-d', '--no-deps', 'app')
        raise
    try:
        compose(target, 'up', '-d', '--no-deps', 'app')
        wait_healthy(target)
    except Exception:
        compose(target, 'stop', 'app')
        print('新版本启动失败，已停止新应用，避免旧程序误写新数据库。')
        print('请按手册恢复上述备份，再从原目录启动旧应用；NapCat 未停止。')
        print('备份文件：' + name)
        raise
    print('更新成功，当前程序目录：' + str(target))
    print('旧目录和镜像已保留。后续在新目录执行更新／诊断；运行数据仍在：' + str(root))


def doctor():
    preflight()
    verify(ROOT)
    compose(ROOT, 'ps')
    print('以下不输出日志或密钥；QQ 登录／OneBot 实际状态请登录面板查看。')
    for port in (8000, 3001, 6099):
        with socket.socket() as probe:
            probe.settimeout(2)
            print(f'127.0.0.1:{port} ' + ('可达' if probe.connect_ex(('127.0.0.1', port)) == 0 else '不可达'))
    print('持久化目录：' + str(runtime_path()))
    compose(ROOT, 'run', '--rm', '--no-deps', '-T', 'app', 'python', '-m', 'backend.server_admin', 'status')


def restore(archive):
    preflight()
    root = runtime_path()
    password = passphrase()
    staging = root.parent / ('runtime-restore-' + stamp())
    staging.mkdir(mode=0o700)
    image = environment()['SHUNGUANG_IMAGE']
    run(
        [
            'docker',
            'run',
            '--rm',
            '-i',
            '--network',
            'none',
            '--user',
            '0',
            '--volume',
            str(Path(archive).resolve()) + ':/input.sgbackup:ro',
            '--volume',
            str(staging) + ':/restore',
            image,
            'python',
            '-m',
            'backend.server_admin',
            'restore',
        ],
        payload={'password': password},
    )
    # Only authenticated and path-checked data has reached staging. Stop before swapping.
    compose(ROOT, 'stop')
    old = root.with_name(root.name + '-before-restore-' + stamp())
    root.rename(old)
    staging.rename(root)
    # Application-only update backups retain the unchanged NapCat session/configuration.
    for relative in ('napcat', 'napcat.env', 'backups'):
        if not (root / relative).exists() and (old / relative).exists():
            shutil.copytree(old / relative, root / relative) if (old / relative).is_dir() else shutil.copy2(
                old / relative, root / relative
            )
    (root / 'backups').mkdir(mode=0o700, exist_ok=True)
    os.chown(root / 'backups', 10001, 10001)
    print('已恢复数据，原目录保留于：' + str(old))
    print('服务保持停止。请确认本目录镜像与备份版本匹配，再运行 docker compose up -d。')


def main():
    parser = argparse.ArgumentParser(description='叶瞬光 Linux 服务器部署与维护')
    parser.add_argument('command', choices=['install', 'doctor', 'update', 'backup', 'restore', 'verify'])
    parser.add_argument('archive', nargs='?')
    parser.add_argument('--with-qq', action='store_true', help='Explicitly opt into the optional NapCat Docker bridge.')
    parser.add_argument(
        '--pip-source',
        choices=['official', 'tencent', 'aliyun'],
        help='Explicit package source; default is official PyPI. No global pip configuration is changed.',
    )
    args = parser.parse_args()
    if args.command == 'verify':
        print(json.dumps(verify(ROOT), ensure_ascii=False, indent=2))
        return
    if args.command == 'install':
        initialize(with_qq=args.with_qq, pip_source=args.pip_source)
    elif args.command == 'doctor':
        doctor()
    elif args.command == 'update':
        if not args.archive:
            parser.error('update 需要新部署包路径')
        update(args.archive)
    elif args.command == 'backup':
        preflight()
        password = passphrase(confirm=True)
        compose(ROOT, 'stop')
        try:
            backup(ROOT, password, full=True)
        finally:
            compose(ROOT, 'up', '-d')
    else:
        if not args.archive:
            parser.error('restore 需要加密备份路径')
        restore(args.archive)


if __name__ == '__main__':
    if os.name == 'nt':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        # Subprocess commands never contain passwords; do not dump their environment/stdin.
        print('操作未完成：' + str(error), file=sys.stderr)
        sys.exit(1)
