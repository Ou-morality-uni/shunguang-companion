"""Apply an explicit wizard opt-out without decrypting or removing QQ data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import config
from backend.app.qq.repository import QQRepository

if config.server_mode():
    raise SystemExit('This wizard action is desktop-only.')
root = config.DATA_DIR / 'qq'
if root.is_dir():
    repository = QQRepository(root)
    connection = repository.connection()
    if connection.enabled:
        connection.enabled = False
        repository.save_connection(connection)
print('QQ connection disabled; existing credentials, policies and records retained.')
