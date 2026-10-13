"""Interactive hidden LAN password setup; only salted hash is persisted."""
import getpass
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.access import save_password

password = getpass.getpass('LAN access password (10+ characters): ')
confirmation = getpass.getpass('Confirm password: ')
if password != confirmation:
    raise SystemExit('Passwords differ; nothing saved.')
try:
    save_password(password)
except ValueError as error:
    raise SystemExit(str(error))
print('LAN access protection saved. Password was not printed.')
