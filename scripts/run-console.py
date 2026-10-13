"""Foreground local server with safe console logs and Windows child cleanup.

The BAT launcher opens the browser outside this process tree. No dependencies,
settings, credentials, or persistent log files are created by this helper.
"""
import argparse
import ctypes
from ctypes import wintypes
from copy import deepcopy
import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
_console_job_handle = None


def bind_console_lifetime():
    """Keep hidden RAG/FFmpeg children in a kill-on-owner-close Windows job."""
    global _console_job_handle
    if os.name != 'nt':
        raise RuntimeError('这个启动方式仅用于 Windows。')

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ('PerProcessUserTimeLimit', ctypes.c_longlong),
            ('PerJobUserTimeLimit', ctypes.c_longlong),
            ('LimitFlags', wintypes.DWORD),
            ('MinimumWorkingSetSize', ctypes.c_size_t),
            ('MaximumWorkingSetSize', ctypes.c_size_t),
            ('ActiveProcessLimit', wintypes.DWORD),
            ('Affinity', ctypes.c_size_t),
            ('PriorityClass', wintypes.DWORD),
            ('SchedulingClass', wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            'ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
            'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    # This non-inheritable handle stays open until this Python process exits.
    # Closing it explicitly would also terminate the current process.
    _console_job_handle = handle


class SafeAccessFormatter(logging.Formatter):
    """Show method, route template and status; never body, headers or query."""
    def __init__(self, paths):
        super().__init__(datefmt='%H:%M:%S')
        from starlette.routing import compile_path
        self.paths = [(compile_path(path)[0], path) for path in paths]

    def format(self, record):
        _, method, target, _, status = record.args
        path = str(target).split('?', 1)[0]
        route = next((template for pattern, template in self.paths if pattern.match(path)), '/[unknown]')
        method = method if method in {'GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'} else 'OTHER'
        return f'{self.formatTime(record, self.datefmt)} INFO: {method} {route} -> {int(status)}'


def main():
    parser = argparse.ArgumentParser(description='瞬光伴行 CMD 后端日志')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('端口需要在 1–65535 之间')
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ['SHUNGUANG_LAN_MODE'] = '0'
    bind_console_lifetime()

    import uvicorn
    from backend.app.main import app
    from backend.app import rag
    logs = deepcopy(uvicorn.config.LOGGING_CONFIG)
    logs['formatters']['default'].update(fmt='%(asctime)s %(levelprefix)s %(message)s', datefmt='%H:%M:%S')
    paths = list(app.openapi()['paths']) + ['/', '/assets/{asset:path}', '/docs', '/openapi.json', '/redoc']
    logs['formatters']['access'] = {'()': SafeAccessFormatter, 'paths': paths}
    try:
        uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='info',
                    log_config=logs, access_log=True, timeout_graceful_shutdown=5)
    finally:
        rag.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except OSError as error:
        print(f'启动失败：无法建立窗口与后端进程的关联（Windows 错误 {error.winerror}）。', file=sys.stderr)
        sys.exit(1)
