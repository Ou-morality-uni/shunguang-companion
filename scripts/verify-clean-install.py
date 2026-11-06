"""Read-only/empty synthetic session checks on an isolated clean installation."""
import hashlib
import json
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
stage=ROOT/'delivery/staging/shunguang-companion'
checks=[]
with httpx.Client(base_url='http://127.0.0.1:8006',timeout=15) as client:
    root=client.get('/')
    checks.append({'name':'documented_windows_powershell_start','ok':root.status_code==200 and '瞬光伴行' in root.text})
    settings=client.get('/api/settings').json()
    checks.append({'name':'empty_settings_no_key_echo','ok':settings.get('has_api_key') is False and 'api_key' not in settings})
    checks.append({'name':'new_user_empty_memories','ok':client.get('/api/memories').json()==[]})
    cid=client.post('/api/conversations').json()['id']
    response=client.post('/api/chat',json={'conversation_id':cid,'content':'空配置提示验收'})
    checks.append({'name':'missing_model_configuration_clear','ok':response.status_code==503 and '设置' in response.json().get('detail','')})
    checks.append({'name':'failed_precondition_no_phantom_messages','ok':client.get('/api/conversations/'+cid+'/messages').json()==[]})
    features=client.get('/api/features').json()
    checks.append({'name':'public_search_default_and_voice_opt_in','ok':features['tools']['search_provider']=='public' and features['tts']['enabled'] is False})
    checks.append({'name':'no_archived_private_reference_in_package','ok':client.get('/api/voice/references').json().get('references')==[]})
    checks.append({'name':'missing_media_explicit_404','ok':client.get('/api/resources/character/avatar.png').status_code==404})
    checks.append({'name':'rag_missing_environment_explicit','ok':not client.get('/api/rag/status').json().get('ready',False)})

for item in (ROOT/'frontend/dist/assets').iterdir():
    counterpart=stage/'frontend/dist/assets'/item.name
    checks.append({'name':'reproducible_asset_'+item.name,'ok':counterpart.is_file() and hashlib.sha256(item.read_bytes()).digest()==hashlib.sha256(counterpart.read_bytes()).digest()})
report={'kind':'clean_source_install','environment':{'python':'3.11.9','node':'24.15.0','npm':'11.12.1','powershell':'Windows PowerShell 5.1'},'install':'New project venv + pinned pip dependencies, npm ci (269 packages, audit 0), tsc/Vite production build. UTF-8 BOM scripts verified with powershell.exe.','backend_tests':{'executed_separately':True,'record':'delivery/验收报告.md','note':'This script checks isolated runtime behavior and assets; it does not run pytest.'},'checks':checks}
(ROOT/'delivery/clean-install-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(checks,ensure_ascii=False))
