"""Container-only administrative commands. Secrets arrive on stdin, never argv."""

import argparse
import io
import json
import os
import secrets
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from backend.app.constants import VERSION

MAGIC = b'SGBAK1\x00'


def derive(password, salt):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    if len(password) < 12:
        raise ValueError('备份口令至少 12 位')
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode())


def backup_archive(output, password, entries, metadata):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    cipher = Cipher(algorithms.AES(derive(password, salt)), modes.GCM(nonce)).encryptor()
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as destination:
        destination.write(MAGIC + salt + nonce)

        class Writer:
            def write(self, data):
                destination.write(cipher.update(data))
                return len(data)

        def safe(info):
            if not (info.isfile() or info.isdir()):
                raise ValueError('备份数据含链接或特殊文件，请先检查')
            return info

        with tarfile.open(fileobj=Writer(), mode='w|gz') as archive:
            raw = json.dumps(metadata).encode()
            info = tarfile.TarInfo('snapshot.json')
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
            for path, name in entries:
                archive.add(path, arcname=name, filter=safe)
        destination.write(cipher.finalize())
        destination.write(cipher.tag)


def restore_archive(source, destination, password):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    destination = Path(destination).resolve()
    if any(destination.iterdir()):
        raise ValueError('恢复暂存目录必须为空')
    with Path(source).open('rb') as encrypted, tempfile.TemporaryFile(dir=destination.parent) as plain:
        if encrypted.read(len(MAGIC)) != MAGIC:
            raise ValueError('备份格式不正确')
        salt, nonce = encrypted.read(16), encrypted.read(12)
        header_size = len(MAGIC) + 28
        size = encrypted.seek(0, 2)
        if size < header_size + 16:
            raise ValueError('备份不完整')
        encrypted.seek(-16, 2)
        tag = encrypted.read(16)
        cipher = Cipher(algorithms.AES(derive(password, salt)), modes.GCM(nonce, tag)).decryptor()
        encrypted.seek(header_size)
        remaining = size - header_size - 16
        while remaining:
            block = encrypted.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError('备份不完整')
            plain.write(cipher.update(block))
            remaining -= len(block)
        plain.write(cipher.finalize())  # Authenticate before extracting any file.
        plain.seek(0)
        with tarfile.open(fileobj=plain, mode='r:gz') as archive:
            members = []
            total = 0
            names = set()
            for member in archive:
                path = destination / member.name
                if (
                    not path.resolve().is_relative_to(destination)
                    or '\\' in member.name
                    or not (member.isfile() or member.isdir())
                    or member.name in names
                    or not (
                        member.name.split('/')[0] in ('data', 'secrets', 'napcat')
                        or member.name in ('snapshot.json', 'napcat.env')
                    )
                ):
                    raise ValueError('备份包含非法路径或链接')
                names.add(member.name)
                total += member.size
                if len(members) >= 100000 or total > 10 * 1024**3:
                    raise ValueError('备份展开超过限制')
                members.append(member)
            for member in members:
                target = destination / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with archive.extractfile(member) as source_file, target.open('xb') as target_file:
                        import shutil

                        shutil.copyfileobj(source_file, target_file, length=1024 * 1024)
                    target.chmod(0o600)
            for path in destination.rglob('*'):
                if os.name != 'nt' and os.geteuid() == 0:
                    os.chown(path, 10001, 10001)
    return json.loads((destination / 'snapshot.json').read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'status', 'backup', 'restore'])
    args = parser.parse_args()
    payload = json.load(sys.stdin) if args.command != 'status' else {}
    if args.command == 'restore':
        metadata = restore_archive('/input.sgbackup', '/restore', payload['password'])
        print('备份验证和恢复完成，版本：' + str(metadata.get('version')))
        return
    from backend.app import access, config
    from backend.app.qq.models import Connection
    from backend.app.qq.repository import QQRepository

    if args.command == 'init':
        if (config.DATA_DIR / 'access.json').exists():
            raise ValueError('已有管理设置，不自动覆盖')
        # Validate and encrypt the connection before writing the login marker.
        if payload.get('bot_id') or payload.get('token'):
            connection = Connection(enabled=True, bot_id=payload['bot_id'], token=payload['token'])
            repository = QQRepository(config.DATA_DIR / 'qq')
            repository.save_connection(connection)
        access.save_password(payload['password'])
        print('管理口令及所选接入配置已初始化；未发送消息。')
    elif args.command == 'status':
        from backend.app.credentials import FileKeyBackend

        FileKeyBackend().cipher()
        print('服务器加密主密钥可读取；管理口令已配置：' + str((config.DATA_DIR / 'access.json').is_file()))
        print('模型已配置：' + str(config.public_config(config.load_config())['configured']))
    else:
        name = payload['name']
        if Path(name).name != name or not name.endswith('.sgbackup'):
            raise ValueError('备份文件名无效')
        directory = Path(os.environ.get('SHUNGUANG_BACKUP_DIR', '/backups'))
        entries = [(config.DATA_DIR, 'data'), (Path(os.environ['SHUNGUANG_MASTER_KEY_FILE']), 'secrets/master.key')]
        if payload.get('full'):
            entries += [(Path('/napcat-backup'), 'napcat'), (Path('/napcat.env'), 'napcat.env')]
        build = config.ROOT / 'server-build.json'
        metadata = {
            'version': VERSION,
            'build': json.loads(build.read_text()) if build.exists() else {},
            'full': bool(payload.get('full')),
            'time': datetime.now(timezone.utc).isoformat(),
        }
        backup_archive(directory / name, payload['password'], entries, metadata)
        print('加密备份已生成。')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # A bad key, archive or setting may contain secrets. Keep console diagnostics fixed.
        print('管理操作失败：请检查配置、权限、备份口令及备份完整性。', file=sys.stderr)
        sys.exit(1)
