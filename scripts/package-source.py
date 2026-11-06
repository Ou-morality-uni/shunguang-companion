"""Reproducible allowlisted source archive: no runtime data, keys, weights/cache."""
import argparse
import hashlib
import json
import re
import os
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,default=ROOT/'delivery/shunguang-companion-source.zip')
parser.add_argument('--include-archived-media',action='store_true',help='Private local copy only; redistribution rights are not confirmed.')
args=parser.parse_args()
allowed_files={'README.md','README.en.md','.gitignore','.gitattributes','pyproject.toml','Install.bat','Start_up.bat','INSTALL_LIST.md'}
allowed_roots={'backend','frontend','scripts','source','delivery','.github'}
delivery_reports={'交付清单.md','验收报告.md','integrated-api-report.json','deepseek-anthropic-report.json','chinese-search-report.json','lan-report.json','browser-report.json','clean-install-report.json','public-search-report.json','runtime-report.json','rag-report.json','gpu-report.json','voiceclone-report.json'}
excluded_dirs={'.git','.venv','.venv-rag','node_modules','dist','__pycache__','.pytest_cache','data','models','output','artifacts','staging','screenshots','.codex','.agents','npm-cache'}
source_extensions={'.py','.md','.json','.txt','.ps1','.tsx','.ts','.css','.html','.toml','.js','.yml','.yaml'}
media_extensions={'.png','.jpg','.webp','.mp4','.mp3','.wav'}
manifest=[]
paths=[]
for directory,children,files in os.walk(ROOT):
    children[:]=[name for name in children if name not in excluded_dirs]
    paths.extend(Path(directory)/name for name in files)
for path in sorted(paths):
    relative=path.relative_to(ROOT)
    if any(part in excluded_dirs for part in relative.parts):continue
    if relative.parts[0] not in allowed_roots and str(relative) not in allowed_files:continue
    if relative.parts[0]=='delivery' and (len(relative.parts)!=2 or path.name not in delivery_reports):continue
    if path.name.startswith('.env') or path.suffix.lower() in {'.bin','.gguf','.safetensors','.sqlite3','.db','.log','.zip'}:continue
    if path.suffix.lower() in media_extensions:
        if not args.include_archived_media or not relative.as_posix().startswith('source/resources/'):continue
    elif path.suffix.lower() not in source_extensions and str(relative) not in allowed_files and not (
        relative.as_posix().startswith('frontend/licenses/')
        and (path.name.startswith('LICENSE') or path.name.endswith('LICENSE'))
    ):continue
    raw=path.read_bytes()
    # Credential assignment scan on source, ignoring test-only literals and scanner itself.
    if path.suffix.lower() not in media_extensions and path.name!='package-source.py' and 'tests' not in relative.parts:
        text=raw.decode('utf-8-sig')
        if re.search(r'\bsk-[A-Za-z0-9]{24,}\b|\btvly-[A-Za-z0-9_-]{24,}\b',text):
            raise SystemExit(f'Potential credential found in {relative}; archive not created.')
    manifest.append({'path':relative.as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
args.output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(args.output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for entry in manifest:
        info=zipfile.ZipInfo('shunguang-companion/'+entry['path'],date_time=(2026,10,12,0,0,0))
        info.compress_type=zipfile.ZIP_DEFLATED
        archive.writestr(info,(ROOT/entry['path']).read_bytes())
    metadata={'format':1,'kind':'clean_source','runtime_data_included':False,'weights_included':False,'archived_media_included':args.include_archived_media,'media_distribution_status':'User-provided local archive; public redistribution rights not recorded.','files':manifest}
    info=zipfile.ZipInfo('shunguang-companion/SOURCE-MANIFEST.json',date_time=(2026,10,12,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
    archive.writestr(info,json.dumps(metadata,ensure_ascii=False,indent=2))
digest=hashlib.sha256(args.output.read_bytes()).hexdigest()
summary={'archive':args.output.name,'sha256':digest,'bytes':args.output.stat().st_size,'source_files':len(manifest),'archived_media_included':args.include_archived_media}
(args.output.parent/(args.output.stem+'.manifest.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
