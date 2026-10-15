"""Cross-platform developer commands using the currently selected Python runtime."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('serve', 'test', 'verify', 'contracts', 'build'))
    args = parser.parse_args()
    npm = shutil.which('npm.cmd') or shutil.which('npm')
    if args.command in ('verify', 'contracts', 'build') and not npm:
        parser.error('Node.js/npm is required for this command.')
    if args.command == 'serve':
        run(
            [
                sys.executable,
                '-m',
                'uvicorn',
                'backend.app.main:app',
                '--host',
                '127.0.0.1',
                '--port',
                '8000',
                '--no-access-log',
            ]
        )
    if args.command in ('verify', 'test'):
        run([sys.executable, '-m', 'pytest'])
    if args.command == 'contracts':
        run([sys.executable, 'scripts/export-openapi.py'])
        run([npm, '--prefix', 'frontend', 'run', 'gen:api'])
    if args.command == 'verify':
        run([sys.executable, '-m', 'ruff', 'check', '.'])
        run([sys.executable, '-m', 'ruff', 'format', '--check', '.'])
        run([sys.executable, 'scripts/export-openapi.py', '--check'])
        run([npm, '--prefix', 'frontend', 'run', 'verify'])
    if args.command == 'build':
        run([npm, '--prefix', 'frontend', 'run', 'build'])


if __name__ == '__main__':
    main()
