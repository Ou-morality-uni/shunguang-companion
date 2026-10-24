"""Discover the local Office engine; run only reviewed, bounded conversion commands."""

import importlib.util
import io
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

INSTALL_URL = 'https://www.libreoffice.org/download/download-libreoffice/'


def safe_package(data):
    from .document_readers import check_archive
    from .filework import WorkError

    check_archive(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            name = entry.filename.lower()
            print_settings = re.fullmatch(r'(?:word|xl|ppt)/printersettings/printersettings[0-9]+\.bin', name)
            if (
                any(
                    marker in name
                    for marker in (
                        'vbaproject',
                        'activex/',
                        'externallinks/',
                        'connections.xml',
                        'querytables/',
                        'altchunk',
                    )
                )
                or (name.endswith('.bin') and (not print_settings or entry.file_size > 1024 * 1024))
                or name.endswith(('.svg', '.html', '.htm'))
            ):
                raise WorkError('此文件包含宏、外部连接或暂不能安全转换的嵌入对象，请先另存为常规副本。', 422)
            if name.startswith('xl/') and name.endswith('.xml'):
                from .office_excel import validate_formula

                for node in ET.fromstring(archive.read(entry)).iter():
                    if (
                        node.tag.rsplit('}', 1)[-1] in ('f', 'formula', 'formula1', 'formula2', 'definedName')
                        and node.text
                    ):
                        validate_formula('=' + node.text.lstrip('='))
            if name.startswith('word/') and name.endswith('.xml'):
                commands = []
                for node in ET.fromstring(archive.read(entry)).iter():
                    if node.tag.rsplit('}', 1)[-1] == 'instrText':
                        commands.append(node.text or '')
                    for key, value in node.attrib.items():
                        if key.rsplit('}', 1)[-1] == 'instr':
                            commands.append(value)
                if any(
                    re.search(r'(?:^|\s)(?:INCLUDETEXT|INCLUDEPICTURE|DDEAUTO|DDE|LINK|DATABASE)\b', text, re.I)
                    for text in (' '.join(commands), ''.join(commands))
                ):
                    raise WorkError('文件包含可能读取其他文件或连接外部数据的外部字段，请先移除或转为普通内容。', 422)
            if name.endswith('.rels'):
                for relation in ET.fromstring(archive.read(entry)):
                    if any(
                        marker in relation.get('Type', '').lower() for marker in ('vbaproject', 'activex', 'oleobject')
                    ):
                        raise WorkError('此文件包含暂不能安全转换的活动对象，请先另存为常规副本。', 422)
                    if relation.get('TargetMode', '').lower() == 'external' and not relation.get('Type', '').endswith(
                        '/hyperlink'
                    ):
                        raise WorkError('文件包含外部资源引用，不会在转换时自动访问。请先将资源嵌入副本。', 422)


def convert(data, suffix, target='pdf', check=lambda: None):
    """Use an owned process/profile and a temporary copy; never overwrite source."""
    from .filework import MAX_FILE_BYTES, WorkError

    executable = find_office()
    if not executable:
        raise WorkError('未检测到 LibreOffice，请先按工具服务中的官方指引安装，再重新检测。', 422)
    if suffix not in ('.docx', '.xlsx', '.pptx') or target not in ('pdf', 'xlsx'):
        raise WorkError('此 Office 转换格式暂不受支持。', 422)
    safe_package(data)
    with tempfile.TemporaryDirectory(prefix='shunguang-office-') as directory:
        root = Path(directory)
        source, output, profile = root / ('source' + suffix), root / 'converted', root / 'profile'
        output.mkdir()
        profile.mkdir()
        (profile / 'registrymodifications.xcu').write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>',
            encoding='utf-8',
        )
        source.write_bytes(data)
        arguments = [
            str(executable),
            '-env:UserInstallation=' + profile.as_uri(),
            '--headless',
            '--norestore',
            '--nodefault',
            '--convert-to',
            target,
            '--outdir',
            str(output),
            str(source),
        ]
        check()
        with (root / 'engine.log').open('wb') as log:
            process = subprocess.Popen(
                arguments,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                start_new_session=os.name != 'nt',
            )
            try:
                deadline = time.monotonic() + 120
                while process.poll() is None:
                    check()
                    if time.monotonic() > deadline or log.tell() > 1024 * 1024:
                        raise WorkError('LibreOffice 转换超时或输出异常，请缩小文件后重试。', 422)
                    time.sleep(0.1)
                result = output / ('source.' + target)
                if process.returncode != 0 or not result.is_file():
                    raise WorkError('LibreOffice 未生成有效成果，请检查文件格式、占用和字体。', 422)
                if result.stat().st_size > MAX_FILE_BYTES:
                    raise WorkError('转换成果超过 20 MiB 上限。', 422)
                check()
                return result.read_bytes()
            finally:
                if process.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(
                            [
                                str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/taskkill.exe'),
                                '/PID',
                                str(process.pid),
                                '/T',
                                '/F',
                            ],
                            capture_output=True,
                            timeout=5,
                            check=False,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


def find_office():
    from . import config

    local = config.ROOT / 'tools/LibreOffice/program' / ('soffice.com' if os.name == 'nt' else 'soffice')
    candidates = [str(local), shutil.which('soffice.com'), shutil.which('soffice'), shutil.which('libreoffice')]
    if os.name == 'nt':
        candidates += [
            str(Path(folder) / 'LibreOffice/program/soffice.com')
            for folder in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'))
            if folder
        ]
    elif os.uname().sysname == 'Darwin':
        candidates.append('/Applications/LibreOffice.app/Contents/MacOS/soffice')
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def capabilities():
    executable = find_office()
    ready, version = False, ''
    if executable:
        try:
            result = subprocess.run(
                [str(executable), '--version'],
                capture_output=True,
                timeout=5,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            version = result.stdout.decode('utf-8', errors='replace').strip()[:160]
            ready = result.returncode == 0 and 'LibreOffice' in version
        except (OSError, subprocess.TimeoutExpired):
            pass
    formats = {}
    for name, library in {
        'docx': 'docx',
        'xlsx': 'openpyxl',
        'pptx': 'pptx',
        'pdf': 'pypdfium2',
        'image': 'PIL',
    }.items():
        formats[name] = {
            'read': importlib.util.find_spec(library) is not None,
            'page_preview': ready
            if name in ('docx', 'xlsx', 'pptx')
            else importlib.util.find_spec(library) is not None,
            'export_pdf': ready and name in ('docx', 'xlsx', 'pptx'),
            'recalculate': ready and name == 'xlsx',
        }
    return {
        'office': {
            'ready': ready,
            'version': version if ready else '',
            'install_url': INSTALL_URL,
            'message': 'Office 页面预览、PDF 导出与 Excel 重算已就绪。'
            if ready
            else '未检测到可用的 LibreOffice；Office 页面预览、Office 转 PDF 与 Excel 重算暂不可用。安装后请重新检测，已有内容阅读不受影响。',
        },
        'formats': formats,
    }
