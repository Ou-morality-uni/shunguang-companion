"""Windows user-scoped credential encryption; never fall back to plaintext."""

import base64
import ctypes
import os
from threading import RLock
from typing import Protocol

VAULT_LOCK = RLock()
from ctypes import wintypes


class DataBlob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def transform(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('当前凭据保存使用 Windows 加密，请为其他平台配置凭据后端。')
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
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


class CredentialBackend(Protocol):
    def encrypt(self, secret: str) -> str: ...
    def decrypt(self, encoded: str) -> str: ...


class WindowsDpapiBackend:
    def encrypt(self, secret: str) -> str:
        return base64.b64encode(transform(secret.encode('utf-8'), decrypt=False)).decode('ascii')

    def decrypt(self, encoded: str) -> str:
        return transform(base64.b64decode(encoded, validate=True), decrypt=True).decode('utf-8')


class KeyringBackend:
    """Non-Windows systems use the OS credential vault, never a plaintext fallback."""

    service = 'shunguang-companion'

    def vault(self):
        import keyring

        backend = keyring.get_keyring()
        # Only OS vaults are accepted; third-party file backends can silently store plaintext.
        allowed = ('keyring.backends.macOS', 'keyring.backends.SecretService', 'keyring.backends.kwallet')
        candidates = [backend]
        if type(backend).__module__ == 'keyring.backends.chainer':
            candidates = backend.backends
        for candidate in candidates:
            if type(candidate).__module__ in allowed:
                return candidate
        raise RuntimeError('系统密钥环不可用，请启用系统凭据服务。')

    def encrypt(self, secret: str) -> str:
        return self.cipher(create=True).encrypt(secret.encode()).decode('ascii')

    def decrypt(self, encoded: str) -> str:
        return self.cipher(create=False).decrypt(encoded.encode('ascii')).decode()

    def cipher(self, *, create):
        from cryptography.fernet import Fernet

        with VAULT_LOCK:
            vault = self.vault()
            key = vault.get_password(self.service, 'encryption-key-v1')
            if key is None:
                if not create:
                    raise RuntimeError('系统密钥环中没有加密密钥，请重新填写凭据。')
                key = Fernet.generate_key().decode('ascii')
                vault.set_password(self.service, 'encryption-key-v1', key)
            return Fernet(key.encode('ascii'))


def encrypt_secret(secret: str) -> str:
    name, backend = ('dpapi', WindowsDpapiBackend()) if os.name == 'nt' else ('keyring', KeyringBackend())
    try:
        return f'{name}:v1:{backend.encrypt(secret)}'
    except Exception:
        raise RuntimeError('无法保存系统凭据，请检查当前账户的密钥存储服务。') from None


def decrypt_secret(encoded: str) -> str:
    try:
        if encoded.startswith('keyring:v1:'):
            return KeyringBackend().decrypt(encoded.removeprefix('keyring:v1:'))
        # Unprefixed values are the legacy Windows DPAPI format.
        return WindowsDpapiBackend().decrypt(encoded.removeprefix('dpapi:v1:'))
    except Exception:
        raise RuntimeError('凭据无法读取；请在原账户运行，或重新填写密钥。') from None
