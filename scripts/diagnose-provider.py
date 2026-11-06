"""Read-only safe network diagnosis; no exception bodies, headers or keys."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import ssl
import truststore
from backend.app.config import load_config
from backend.app.providers import headers,endpoint

config=load_config()
results=[]
for system_proxy in (False,True,'windows_trust'):
    try:
        context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if system_proxy=='windows_trust' else True
        response=httpx.get(endpoint(config.llm_base_url,'models'),headers=headers(config),timeout=15,trust_env=system_proxy is not False,verify=context,follow_redirects=False)
        results.append({'system_proxy':system_proxy,'status':response.status_code,'models':[item.get('id') for item in response.json().get('data',[])] if response.status_code==200 else []})
    except Exception as error:
        diagnostic=str(error).lower()
        classification='certificate_verification' if 'certificate' in diagnostic else 'tls' if 'ssl' in diagnostic or 'tls' in diagnostic else 'dns' if 'name' in diagnostic or 'resolve' in diagnostic else 'network'
        results.append({'system_proxy':system_proxy,'error_type':type(error).__name__,'cause_type':type(error.__cause__).__name__,'classification':classification})
print(json.dumps(results,ensure_ascii=False))
