"""Real LAN-bound isolated server and protection check; no firewall changes."""
import json,os,secrets,socket,sys,tempfile,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx,uvicorn
from backend.app import config,access

addresses=[row[4][0] for row in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET) if not row[4][0].startswith(('127.','169.254.'))]
if not addresses:raise SystemExit('No local IPv4 interface found; device test not claimed.')
address=addresses[0]
folder=config.ROOT/'artifacts/qa/lan-data';folder.mkdir(parents=True,exist_ok=True)
config.DATA_DIR=folder
os.environ['SHUNGUANG_LAN_MODE']='1'
os.environ['SHUNGUANG_ALLOWED_HOSTS']=','.join(addresses)
password=secrets.token_urlsafe(20)
access.save_password(password)
from backend.app.main import app
server=uvicorn.Server(uvicorn.Config(app,host='0.0.0.0',port=8004,access_log=False,log_level='error'))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
deadline=time.monotonic()+10
while not server.started and time.monotonic()<deadline:time.sleep(.1)
report={'kind':'real_lan_socket','phone_device_tested':False,'checks':[]}
try:
    with httpx.Client(base_url=f'http://{address}:8004',timeout=10,trust_env=False) as client:
        home=client.get('/')
        locked=client.get('/api/settings')
        status=client.get('/api/auth/status').json()
        login=client.post('/api/auth/login',json={'password':password})
        settings=client.get('/api/settings')
        report['checks']=[{'name':'lan_home','ok':home.status_code==200},{'name':'data_protected','ok':locked.status_code==401 and status['required'] and not status['authenticated']},{'name':'login_cookie','ok':login.status_code==200 and 'HttpOnly' in login.headers.get('set-cookie','')},{'name':'authorized_api','ok':settings.status_code==200 and settings.json()['has_api_key'] is False}]
except Exception as error:
    report['checks'].append({'name':'network','ok':False,'error_type':type(error).__name__})
finally:
    server.should_exit=True;thread.join(timeout=10)
    target=config.ROOT/'delivery/lan-report.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
