"""Safe configured search authentication diagnosis; never output key/body."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.transport import ssl_context
from backend.app.feature_config import load
import httpx

settings=load().tools
key=settings.api_key.get_secret_value()
report={'provider':settings.search_provider,'has_key':bool(key),'expected_key_prefix':key.startswith('tvly-')}
if settings.search_provider=='tavily' and key:
    try:
        response=httpx.get('https://api.tavily.com/usage',headers={'Authorization':'Bearer '+key},timeout=15,verify=ssl_context())
        report['status']=response.status_code
        if response.status_code in (401,403):
            text=response.text.lower()
            report['classification']='invalid_credential' if 'invalid' in text or 'unauthor' in text else 'access_denied'
    except Exception as error:
        report['error_type']=type(error).__name__
print(json.dumps(report))
