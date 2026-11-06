"""Local file tasks: explicit grants, bounded operations and a durable undo journal.

This is a file API, not a process sandbox. It never executes file contents.
"""

import ctypes
import hashlib
import os
import stat
import sys
from pathlib import Path, PureWindowsPath

from . import config
from .work_models import BLOCKED, MAX_FILE_BYTES, WorkError


def local_request(request):
    """Never trust Forwarded headers or a LAN login as local file authorization."""
    if request is None or request.client is None:
        return False
    import ipaddress

    peer = request.client.host
    if peer == 'testclient' and request.url.hostname == 'testserver':
        return True
    try:
        return ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return False


def no_link(path):
    value = path.lstat()
    if stat.S_ISLNK(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400:
        raise WorkError('不允许通过符号链接、目录联接或重解析点访问文件。', 403)
    if stat.S_ISREG(value.st_mode) and value.st_nlink != 1:
        raise WorkError('不允许操作存在硬链接的文件。', 403)
    return value


def move_exclusive(source, destination):
    """Atomic move that cannot overwrite another program's new destination."""
    if os.name == 'nt':
        os.rename(source, destination)
    elif sys.platform.startswith('linux'):
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, 'renameat2', None)
        if rename is None:
            raise WorkError('当前系统不支持安全的不覆盖移动。', 422)
        if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
            raise OSError(ctypes.get_errno(), 'exclusive move failed')
    else:
        raise WorkError('当前系统不支持安全的不覆盖移动。', 422)


class PathAccess:
    def protected(self, path):
        if path == self.upload_root or self.upload_root in path.parents:
            return
        if path == self.output_root or self.output_root in path.parents:
            return
        protected = [config.DATA_DIR.resolve(), config.ROOT / '.git', config.ROOT / '.codex']
        if any(path == item or item in path.parents for item in protected):
            raise WorkError('应用数据、凭据和内部管理目录不属于工作文件范围。', 403)

    def default_output_workspace(self):
        with self.gate:
            for parent in self.output_root.parents:
                no_link(parent)
            self.output_root.mkdir(exist_ok=True)
            no_link(self.output_root)
            existing = next(
                (item for item in self.store.list_workspaces() if Path(item['path']) == self.output_root), None
            )
            if existing:
                self.root(existing['id'])
                workspace = existing
            else:
                workspace = self.grant(str(self.output_root))
            self.store.set_output_workspace(workspace['id'])
            return workspace

    def grant(self, raw_path):
        path = Path(raw_path.strip())
        if not path.is_absolute() or str(path).startswith(('\\\\', '//')) or path == Path(path.anchor):
            raise WorkError('请选择本机已有的具体文件夹，不能授权整个磁盘或网络共享。', 422)
        for part in (path, *path.parents):
            no_link(part)
        path = path.resolve(strict=True)
        if not path.is_dir():
            raise WorkError('工作路径必须是已有文件夹。', 422)
        self.protected(path)
        if any(part.casefold() in BLOCKED or part.casefold().startswith('.env') for part in path.parts):
            raise WorkError('不能授权凭据或内部管理目录。', 403)
        value = no_link(path)
        with self.gate:
            return self.store.grant_workspace(str(path), f'{value.st_dev}:{value.st_ino}')

    def root(self, workspace_id):
        workspace = self.store.get_workspace(workspace_id)
        if not workspace or not workspace['enabled']:
            raise WorkError('工作文件夹尚未授权或已撤销授权。', 403)
        path = Path(workspace['path'])
        for part in (path, *path.parents):
            no_link(part)
        value = no_link(path)
        if not stat.S_ISDIR(value.st_mode) or workspace['identity'] != f'{value.st_dev}:{value.st_ino}':
            raise WorkError('工作文件夹已被替换，请重新授权。', 403)
        self.protected(path)
        return path

    def path(self, root, relative):
        # Apply Windows rules on every platform, including ADS and device names.
        relative = relative.replace('\\', '/')
        if relative == '.':
            return root
        parts = relative.split('/')
        if PureWindowsPath(relative).is_absolute() or PureWindowsPath(relative).drive:
            raise WorkError('文件路径必须相对于授权文件夹。', 403)
        for part in parts:
            if (
                part in ('', '.', '..')
                or part.rstrip(' .') != part
                or any(char in part for char in ':<>"|?*')
                or any(ord(char) < 32 for char in part)
                or PureWindowsPath(part).is_reserved()
                or part.casefold() in BLOCKED
                or part.casefold().startswith(('.env', '.shunguang-'))
            ):
                raise WorkError('路径包含越界、保留名称或受保护的内容。', 403)
        target = root
        root_device = root.stat().st_dev
        for part in parts:
            target = target / part
            self.protected(target)
            if target.exists() or target.is_symlink():
                value = no_link(target)
                if value.st_dev != root_device:
                    raise WorkError('不能通过挂载目录扩大工作范围。', 403)
        if not target.resolve(strict=False).is_relative_to(root):
            raise WorkError('文件路径超出授权范围。', 403)
        return target

    def fingerprint(self, path):
        if not path.exists():
            if path.is_symlink():
                no_link(path)
            return None
        value = no_link(path)
        if not stat.S_ISREG(value.st_mode):
            raise WorkError('此操作仅支持普通文件，不能修改或删除整个目录。', 422)
        if value.st_size > MAX_FILE_BYTES:
            raise WorkError('基础文件任务每个文件最多支持 20 MiB。', 422)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        after = no_link(path)
        if (value.st_ino, value.st_mtime_ns, value.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
            raise WorkError('文件正在被其他程序修改，请稍后重试。')
        return {'sha256': digest.hexdigest(), 'bytes': value.st_size, 'mode': stat.S_IMODE(value.st_mode)}
