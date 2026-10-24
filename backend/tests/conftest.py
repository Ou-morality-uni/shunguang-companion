"""Offline defaults. No user data, DNS, model weights or paid APIs in unit tests."""

import pytest

from backend.app import access, config, rag


@pytest.fixture(autouse=True)
def isolate_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(access, 'allowed_hosts', lambda: {'localhost', '127.0.0.1', '::1'})
    monkeypatch.setattr(rag, 'status', lambda: {'ready': False})
    monkeypatch.delenv('SHUNGUANG_LAN_MODE', raising=False)


@pytest.fixture(autouse=True)
def platform_credentials(monkeypatch):
    import os

    from backend.app import credentials

    if os.name == 'nt':
        return
    secrets = {}

    class TestVault:
        def set_password(self, service, account, password):
            secrets[(service, account)] = password

        def get_password(self, service, account):
            return secrets.get((service, account))

    monkeypatch.setattr(credentials.KeyringBackend, 'vault', lambda _: TestVault())


@pytest.fixture(autouse=True)
def offline_background_memory(monkeypatch):
    from backend.app import memory_jobs

    def offline_model(value):
        raise RuntimeError('Unrelated offline tests do not call background model services')

    monkeypatch.setattr(memory_jobs, 'build_memory_model', offline_model)
