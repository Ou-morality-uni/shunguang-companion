"""Windows user-scoped credential encryption; never fall back to plaintext."""

import base64
import ctypes
import os
from ctypes import wintypes


class DataBlob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def transform(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('当前凭据保存使用 Windows 加密，请为其他平台配置凭据后端。')
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = DataBlob()
    # UI forbidden, user scoped; do not use machine-wide protection.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError('无法读取或保存加密密钥，请使用当前 Windows 账户重新填写。')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(output.data)


def encrypt_secret(secret: str) -> str:
    return base64.b64encode(transform(secret.encode('utf-8'), decrypt=False)).decode('ascii')


def decrypt_secret(encoded: str) -> str:
    return transform(base64.b64decode(encoded, validate=True), decrypt=True).decode('utf-8')
