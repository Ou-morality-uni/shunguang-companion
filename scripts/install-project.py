"""Complete Windows installation with pinned dependencies and a local install list."""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'data/install'
ENV = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
       'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1'}


def run(arguments, *, capture=False, check=True, timeout=None):
    result = subprocess.run([str(arg) for arg in arguments], cwd=ROOT, env=ENV,
                            capture_output=capture, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if check and result.returncode:
        raise RuntimeError('Command failed: ' + Path(str(arguments[0])).name + '; see the installation window above')
    return result


def preflight(rag_only=False):
    if os.name != 'nt' or sys.version_info[:2] != (3, 11) or struct.calcsize('P') != 8:
        raise RuntimeError('Use 64-bit Windows and Python 3.11. This installer does not install Python or Node.js.')
    if not rag_only:
        if not shutil.which('node') or not shutil.which('npm.cmd'):
            raise RuntimeError('Node.js 24 and npm are required; reopen the terminal after installing them.')
        if not run(['node', '--version'], capture=True).stdout.strip().startswith('v24.'):
            raise RuntimeError('Node.js 24 is required.')
    if (ROOT / 'data/companion.sqlite3').exists():
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1) as response:
                health = json.load(response)
            if isinstance(health, dict) and health.get('storage') == 'sqlite' and health.get('stage') == 'Web 功能集成':
                raise RuntimeError('Close the running backend CMD window before installing or updating.')
        except (OSError, ValueError):
            pass
    if shutil.disk_usage(ROOT).free < 12 * 1024**3:
        raise RuntimeError('At least 12 GiB of free disk space is required for dependencies, model and download cache.')


def create_environment(name):
    python = ROOT / name / 'Scripts/python.exe'
    if not python.is_file():
        run([sys.executable, '-m', 'venv', ROOT / name])
    version = run([python, '-c', 'import sys;print("%s.%s"%sys.version_info[:2])'], capture=True).stdout.strip()
    if version != '3.11':
        raise RuntimeError(f'{name} uses another Python version; preserve your data and create a Python 3.11 environment.')
    return python


def vc_runtime_present():
    try:
        for name in ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
            ctypes.WinDLL(name, winmode=0x800)  # Load only from System32.
        return True
    except OSError:
        return False


def ensure_vc_runtime(receipt, *, force=False):
    if not force and vc_runtime_present():
        receipt['vc_runtime'] = {'action': 'existing_system_runtime'}
        return
    print('Missing Microsoft Visual C++ runtime. Downloading the signed official installer; Windows may request administrator approval.', flush=True)
    url = 'https://aka.ms/vc14/vc_redist.x64.exe'
    target = STATE / 'vc_redist.x64.exe'
    temporary = target.with_suffix('.partial')
    hasher = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=90) as response, temporary.open('wb') as output:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > 128 * 1024 * 1024:
                raise RuntimeError('Unexpected Visual C++ runtime download size')
            output.write(block)
            hasher.update(block)
    temporary.replace(target)
    receipt['vc_runtime'] = {'action': 'downloaded_official_installer', 'source': url,
                             'bytes': size, 'sha256': hasher.hexdigest()}
    result = run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                  'scripts/install-vc-runtime.ps1', '-InstallerPath', target], check=False)
    if result.returncode == 3010:
        receipt['vc_runtime']['restart_required'] = True
        raise RuntimeError('Windows requested a restart. Restart Windows, then rerun Install.bat.')
    if result.returncode not in (0, 1638) or not vc_runtime_present():
        raise RuntimeError('Visual C++ runtime was not installed. Resolve the Windows permission/runtime issue and retry.')
    receipt['vc_runtime']['action'] = 'downloaded_and_installed'


def gpu_candidate():
    executable = shutil.which('nvidia-smi')
    if not executable:
        return False
    try:
        summary = run([executable], capture=True, check=False, timeout=10)
        version = re.search(r'CUDA Version:\s*(\d+)\.(\d+)', summary.stdout)
        memory = run([executable, '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
                     capture=True, check=False, timeout=10)
        return bool(version and tuple(map(int, version.groups())) >= (12, 8)
                    and any(int(line.strip()) >= 6000 for line in memory.stdout.splitlines() if line.strip().isdigit()))
    except (OSError, subprocess.TimeoutExpired):
        return False


def install_rag(args, receipt):
    python = create_environment('.venv-rag')
    gpu = not args.cpu and gpu_candidate()
    index = 'https://download.pytorch.org/whl/cu128' if gpu else 'https://download.pytorch.org/whl/cpu'
    receipt['torch_index'] = index
    print('[RAG] Installing ' + ('CUDA 12.8' if gpu else 'CPU') + ' PyTorch.', flush=True)
    version = run([python, '-c', 'import torch;print(torch.__version__)'], capture=True, check=False).stdout.strip()
    torch_args = [python, '-m', 'pip', 'install', 'torch==2.11.0', '--index-url', index,
                  '--report', STATE / 'torch-pip.json', '--disable-pip-version-check']
    if version and version != '2.11.0' + ('+cu128' if gpu else '+cpu'):
        torch_args += ['--force-reinstall']
    run(torch_args)
    receipt['pip_reports'].append('torch-pip.json')
    run([python, '-m', 'pip', 'install', '-r', 'backend/requirements-rag.lock.txt',
         '--index-url', 'https://pypi.org/simple', '--report', STATE / 'rag-pip.json', '--disable-pip-version-check'])
    receipt['pip_reports'].append('rag-pip.json')
    run([python, '-m', 'pip', 'check'])
    imported = run([python, '-c', 'import torch; print(torch.__version__)'], capture=True, check=False)
    if imported.returncode and any(marker in imported.stderr.lower() for marker in ('dll', 'winerror 126', 'winerror 127')):
        print('[RAG] PyTorch reported a DLL error; updating the signed Microsoft runtime once.', flush=True)
        ensure_vc_runtime(receipt, force=True)
        imported = run([python, '-c', 'import torch; print(torch.__version__)'], capture=True, check=False)
    if imported.returncode:
        raise RuntimeError('PyTorch could not import after dependency installation; check the installed architecture and Windows runtime.')
    if gpu:
        probe = run([python, '-c', 'import torch;assert torch.cuda.is_available();x=torch.ones((8,8),device="cuda");assert torch.isfinite(x@x).all();print(torch.cuda.get_device_name(0))'], capture=True, check=False)
        if probe.returncode:
            print('[RAG] CUDA execution failed; installing the CPU build instead.', flush=True)
            receipt['cuda_fallback'] = True
            receipt['torch_index'] = 'https://download.pytorch.org/whl/cpu'
            run([python, '-m', 'pip', 'install', 'torch==2.11.0', '--force-reinstall', '--no-deps',
                 '--index-url', receipt['torch_index'], '--report', STATE / 'torch-pip.json', '--disable-pip-version-check'])
            run([python, '-m', 'pip', 'check'])
    if args.skip_model:
        (ROOT / '.venv-rag/rag-runtime.json').write_text('{"verified":false}', encoding='utf-8')
        receipt['retrieval'] = 'dependencies_only; model and index skipped'
        return
    receipt['stage'] = 'model_download'
    run([python, 'scripts/download-rag-model.py', '--source', args.model_source])
    receipt['stage'] = 'model_inference_and_index'
    run([python, 'scripts/setup-project.py', 'retrieval', '--report', STATE / 'retrieval.json'])
    receipt['retrieval'] = json.loads((STATE / 'retrieval.json').read_text(encoding='utf-8'))


def write_receipt(receipt):
    STATE.mkdir(parents=True, exist_ok=True)
    receipt['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    (STATE / 'result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Install list / 本次安装清单', '',
             f'- Status / 状态：**{receipt["status"]}**', f'- Last stage / 最后阶段：`{receipt["stage"]}`',
             f'- Scope / 范围：`{receipt.get("scope", "complete_project")}`',
             f'- UTC：{receipt["finished_at_utc"]}',
             '- Python / Node.js：使用已安装的基础运行时，脚本没有下载它们。',
             '- 本次 pip 处理的包可能来自网络或缓存；“已存在”不代表本次下载。',
             '- 本文件不记录 API 密钥、聊天、用户事实或电脑名称。', '']
    for environment, report_file in (('.venv', 'backend-pip.json'), ('.venv-rag', 'rag-pip.json')):
        python = ROOT / environment / 'Scripts/python.exe'
        if not python.is_file():
            continue
        result = run([python, '-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'], capture=True, check=False)
        if result.returncode:
            continue
        actions = set()
        for name in {report_file, 'torch-pip.json' if environment == '.venv-rag' else report_file}:
            path = STATE / name
            if path.is_file() and name in receipt.get('pip_reports', []):
                actions.update(item['metadata']['name'].lower().replace('_', '-')
                               for item in json.loads(path.read_text(encoding='utf-8')).get('install', []))
        lines += [f'## {environment} Python packages', '', '| Package | Version | 本次处理 |', '|---|---|---|']
        for package in json.loads(result.stdout):
            action = '下载或缓存安装' if package['name'].lower().replace('_', '-') in actions else '已存在 / venv自带'
            lines.append(f'| {package["name"]} | {package["version"]} | {action} |')
        lines.append('')
    if receipt.get('frontend'):
        lock = json.loads((ROOT / 'frontend/package-lock.json').read_text(encoding='utf-8'))
        lines += ['## Frontend npm packages', '', '| Package | Version | Source |', '|---|---|---|']
        for location, package in sorted(lock.get('packages', {}).items()):
            if location and (ROOT / 'frontend' / location).is_dir():
                name = location.rsplit('node_modules/', 1)[-1]
                lines.append(f'| {name} | {package.get("version", "unknown")} | npm registry / cache |')
        lines += ['', '- Frontend build output：`frontend/dist/`', '']
    provenance = ROOT / 'source/resources/models/bge-m3/model-provenance.json'
    if provenance.is_file() and receipt.get('retrieval'):
        model = json.loads(provenance.read_text(encoding='utf-8'))
        lines += ['## BGE-M3 model files', '', '| File | Bytes | SHA256 |', '|---|---:|---|']
        for item in model['files']:
            lines.append(f'| {item["filename"]} | {item["bytes"]} | `{item["sha256"]}` |')
        distribution = model.get('distribution', {})
        lines += ['', f'- Source：{distribution.get("type", "official_pinned_download")}',
                  f'- Release：{distribution.get("release_url", "not used")}',
                  '- Destination：`source/resources/models/bge-m3/`', '']
    lines += ['## Local storage / 本机存储', '',
              '- SQLite：`data/companion.sqlite3`；新安装为空，已有数据库保持。',
              '- Qdrant：`data/rag/qdrant/`；从随仓库附带的资料构建。',
              '- Index state：`data/rag/index-state.json`。',
              '- Model cache：`data/install/model-cache/`；中断时保留以便续传。',
              '- Detailed receipt：`data/install/result.json`。',
              '- 使用自己在设置界面填写的 API；安装过程没有调用聊天或声音服务。', '']
    if receipt.get('vc_runtime'):
        lines += ['## Microsoft Visual C++ runtime', '',
                  '- Action：`' + receipt['vc_runtime']['action'] + '`']
        if receipt['vc_runtime'].get('source'):
            lines += ['- Source：' + receipt['vc_runtime']['source'],
                      '- SHA256：`' + receipt['vc_runtime']['sha256'] + '`']
    (ROOT / 'data/install-list.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cpu', action='store_true')
    parser.add_argument('--rag-only', action='store_true')
    parser.add_argument('--skip-frontend', action='store_true')
    parser.add_argument('--skip-model', action='store_true')
    parser.add_argument('--model-source', choices=('release', 'official'), default='release')
    args = parser.parse_args()
    receipt = {'status': 'failed', 'stage': 'preflight', 'started_at_utc': datetime.now(timezone.utc).isoformat(),
               'model_source': args.model_source, 'frontend': False, 'pip_reports': [],
               'scope': 'retrieval_only' if args.rag_only else 'complete_project'}
    try:
        preflight(args.rag_only)
        STATE.mkdir(parents=True, exist_ok=True)
        receipt['stage'] = 'system_runtime'
        ensure_vc_runtime(receipt)
        if not args.rag_only:
            receipt['stage'] = 'backend_dependencies'
            print('[1/5] Installing backend dependencies.', flush=True)
            python = create_environment('.venv')
            run([python, '-m', 'pip', 'install', '-r', 'backend/requirements.lock.txt',
                 '--index-url', 'https://pypi.org/simple', '--report', STATE / 'backend-pip.json', '--disable-pip-version-check'])
            receipt['pip_reports'].append('backend-pip.json')
            run([python, '-m', 'pip', 'check'])
            if not args.skip_frontend:
                receipt['stage'] = 'frontend_dependencies_and_build'
                print('[2/5] Installing frontend dependencies and building.', flush=True)
                run([shutil.which('npm.cmd'), '--prefix', 'frontend', 'ci', '--no-audit', '--no-fund'])
                run([shutil.which('npm.cmd'), '--prefix', 'frontend', 'run', 'build'])
                receipt['frontend'] = True
            receipt['stage'] = 'database_and_media'
            print('[3/5] Preparing local SQLite storage and checking media.', flush=True)
            run([python, 'scripts/setup-project.py', 'application', '--report', STATE / 'application.json'])
            receipt['application'] = json.loads((STATE / 'application.json').read_text(encoding='utf-8'))
        receipt['stage'] = 'retrieval_dependencies'
        print('[4/5] Installing retrieval dependencies and pinned BGE-M3.', flush=True)
        install_rag(args, receipt)
        receipt['stage'] = 'complete'
        receipt['status'] = 'partial' if args.skip_model or args.skip_frontend else 'success'
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        receipt['error_type'] = type(exc).__name__
        print('Installation failed at ' + receipt['stage'] + ': ' + str(exc), flush=True)
        print('Fix the reported problem, then rerun Install.bat. Existing personal data is preserved.', flush=True)
    finally:
        try:
            write_receipt(receipt)
            print('Install list: data/install-list.md', flush=True)
        except (OSError, ValueError, subprocess.SubprocessError):
            receipt['status'] = 'failed'
            print('Installation failed: could not write the required install list.', flush=True)
    if receipt['status'] in ('success', 'partial'):
        if args.rag_only:
            print('[5/5] Retrieval installation ' + receipt['status'] + '.', flush=True)
        else:
            print('[5/5] Installation ' + receipt['status'] + '. Run Start_up.bat to open the app.', flush=True)
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
