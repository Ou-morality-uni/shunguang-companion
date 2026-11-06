"""Linux host-script rehearsal: real files/admin, simulated Docker boundary only."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch


def bundle(directory, build):
    directory.mkdir()
    (directory / 'program.txt').write_text('program-' + build)
    manifest = {
        'format': 1,
        'platform': 'linux/amd64',
        'build': build,
        'files': {'program.txt': hashlib.sha256((directory / 'program.txt').read_bytes()).hexdigest()},
    }
    (directory / 'manifest.json').write_text(json.dumps(manifest))


def main():
    with tempfile.TemporaryDirectory(prefix='deployment-rehearsal-') as temporary:
        root = Path(temporary)
        installed = root / 'installed'
        bundle(installed, '0.7.0-old')
        shutil.copyfile('/deployment/manage.py', installed / 'manage.py')
        spec = importlib.util.spec_from_file_location('deployment', installed / 'manage.py')
        manager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manager)
        source = root / 'new'
        bundle(source, '0.7.0-new')
        archive = root / 'new.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            for path in source.iterdir():
                output.write(path, 'ye-shunguang-server-lite/' + path.name)
        real_run = subprocess.run
        calls = []
        fail_build = False

        def docker(args, **kwargs):
            nonlocal fail_build
            calls.append(list(args))
            if args[:2] == ['docker', 'version']:
                return subprocess.CompletedProcess(args, 0, stdout='29.0.0', stderr='')
            if args[:2] == ['docker', 'ps']:
                return subprocess.CompletedProcess(args, 0, stdout='', stderr='')
            if 'build' in args and kwargs.get('cwd') != installed and fail_build:
                raise subprocess.CalledProcessError(1, args)
            if 'backend.server_admin' in args:
                values = manager.environment(kwargs['cwd'])
                runtime = Path(values['RUNTIME_DIR'])
                env = dict(
                    os.environ,
                    SHUNGUANG_MODE='server',
                    SHUNGUANG_DATA_DIR=str(runtime / 'data'),
                    SHUNGUANG_MASTER_KEY_FILE=str(runtime / 'secrets/master.key'),
                    SHUNGUANG_BACKUP_DIR=str(runtime / 'backups'),
                )
                command = args[args.index('backend.server_admin') + 1]
                result = real_run(
                    [sys.executable, '-m', 'backend.server_admin', command],
                    input=kwargs.get('input'),
                    text=True,
                    env=env,
                    check=True,
                    capture_output=True,
                )
                for path in (runtime / 'data').rglob('*'):
                    os.chown(path, 10001, 10001)
                return result
            if 'ps' in args:
                return subprocess.CompletedProcess(
                    args, 0, stdout='[{"State":"running","Health":"healthy"}]', stderr=''
                )
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

        with (
            patch('subprocess.run', side_effect=docker),
            patch('shutil.which', return_value='/usr/bin/docker'),
            patch('builtins.input', return_value='10001'),
            patch('getpass.getpass', return_value='offline-admin-password'),
        ):
            manager.initialize()
            runtime = manager.runtime_path()
            socket_config = json.loads((runtime / 'napcat/config/onebot11.json').read_text())['network'][
                'websocketServers'
            ][0]
            assert socket_config['messagePostFormat'] == 'array'
            assert socket_config['enableForcePushEvent'] is True
            assert socket_config['reportSelfMessage'] is False
            key = (runtime / 'secrets/master.key').read_bytes()
            (runtime / 'data/sentinel.txt').write_text('keep-server-messages')
            manager.initialize()
            assert (runtime / 'secrets/master.key').read_bytes() == key
            calls.clear()
            fail_build = True
            try:
                manager.update(archive)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError('Expected simulated build failure')
            assert not any('stop' in call for call in calls), 'Build failure stopped the old service'
            fail_build = False
            manager.update(archive)  # Retry the same package after its build failed.
            assert (runtime / 'data/sentinel.txt').read_text() == 'keep-server-messages'
            assert (runtime / 'secrets/master.key').read_bytes() == key
            releases = Path(manager.environment()['RELEASES_DIR'])
            assert manager.environment(releases / '0.7.0-new')['RUNTIME_DIR'] == str(runtime)
            assert list((runtime / 'backups').glob('*.sgbackup'))
    print(
        json.dumps(
            {
                'deployment_rehearsal': 'passed',
                'docker_boundary': 'simulated',
                'admin_encryption_and_backup': 'real',
                'real_qq': False,
            }
        )
    )


if __name__ == '__main__':
    main()
