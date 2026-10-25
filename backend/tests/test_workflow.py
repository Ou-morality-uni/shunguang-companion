from pathlib import Path

import yaml


def test_ci_workflow_parses_with_executable_run_steps():
    path = Path(__file__).resolve().parents[2] / '.github/workflows/ci.yml'
    workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert workflow['jobs']
    for job in workflow['jobs'].values():
        for step in job['steps']:
            if 'run' in step:
                assert isinstance(step['run'], str) and step['run'].strip()
