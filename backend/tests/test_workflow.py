import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def test_ci_workflow_parses_with_executable_run_steps():
    path = Path(__file__).resolve().parents[2] / '.github/workflows/ci.yml'
    workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert workflow['jobs']
    for job in workflow['jobs'].values():
        for step in job['steps']:
            if 'run' in step:
                assert isinstance(step['run'], str) and step['run'].strip()


@pytest.mark.skipif(sys.platform != 'win32', reason='Retrieval CI uses the Windows runner shell')
def test_retrieval_ci_check_ignores_conflicting_runner_packages(tmp_path):
    runner = tmp_path / 'runner-python'
    subprocess.run([sys.executable, '-m', 'venv', str(runner)], check=True, capture_output=True, timeout=60)
    python = runner / 'Scripts/python.exe'
    site = runner / 'Lib/site-packages'
    # Distribution metadata reproduces the hosted runner conflict without installing or executing pipx.
    for name, version, requirement in [
        ('filelock', '3.32.3', ''),
        ('pipx', '1.18.4', 'Requires-Dist: filelock>=4.2\n'),
    ]:
        metadata = site / f'{name}-{version}.dist-info/METADATA'
        metadata.parent.mkdir()
        metadata.write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n{requirement}', encoding='utf-8')
    dirty = subprocess.run([str(python), '-m', 'pip', 'check'], capture_output=True, text=True, timeout=30)
    assert dirty.returncode != 0 and 'pipx 1.18.4' in dirty.stdout and 'filelock' in dirty.stdout

    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    )
    commands = [step['run'].strip() for step in workflow['jobs']['retrieval']['steps'] if 'run' in step]
    # Exercise the real setup/check commands, leaving network-dependent dependency downloads to integration checks.
    selected = [command for command in commands if ' -m venv ' in command or command.endswith('-m pip check')]
    assert any(command.endswith('-m pip check') for command in selected)
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "Set-Alias -Name python -Value '" + str(python).replace("'", "''") + "'",
    ]
    for command in selected:
        lines += [command, 'if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }']
    script = tmp_path / 'check-retrieval.ps1'
    script.write_text('\n'.join(lines), encoding='utf-8-sig')
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
