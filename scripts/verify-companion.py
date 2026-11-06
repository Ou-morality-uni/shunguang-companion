"""Real integrated acceptance in isolated QA data, using a few bounded calls."""
import json
import time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
client=httpx.Client(base_url='http://127.0.0.1:8002',timeout=180)
report={'kind':'real_integrated_api','checks':[],'synthetic_user_facts':True}


def call(method,path,body=None):
    response=client.request(method,path,json=body)
    if response.status_code>=400:
        raise RuntimeError(f'API {path} failed with {response.status_code}')
    return response.json()


def chat(cid,text):
    started=time.monotonic()
    first=None;events=[]
    with client.stream('POST','/api/chat',json={'conversation_id':cid,'content':text}) as response:
        if response.status_code!=200:raise RuntimeError('Chat acceptance failed')
        kind=''
        for line in response.iter_lines():
            if line.startswith('event: '):kind=line[7:]
            if line.startswith('data: '):
                data=json.loads(line[6:]);events.append((kind,data))
                if kind=='delta' and first is None:first=time.monotonic()-started
    done=next((data for name,data in reversed(events) if name=='done'),None)
    if done is None:raise RuntimeError('Stream did not complete')
    return done,{'first_text_seconds':round(first or 0,3),'total_seconds':round(time.monotonic()-started,3),'delta_events':sum(name=='delta' for name,_ in events)}


try:
    cid=call('POST','/api/conversations')['id']
    identity,perf=chat(cid,'你是谁？简短介绍一下自己，不要剧透。')
    report['checks'].append({'name':'role_identity','ok':'叶瞬光' in identity['content'] and '云岿山' in identity['content'] and '基于' not in identity['content'],'answer':identity['content'],'sources':identity.get('sources',[]),'performance':perf})
    statement,_=chat(cid,'我住在上海。我喜欢乌龙茶。')
    candidates=call('POST','/api/memories/summarize',{'conversation_id':cid})['candidates']
    selected=[{'id':item['id'],'key':item['key'],'value':item['value']} for item in candidates if item['value'] in ('上海','乌龙茶')]
    saved=call('POST','/api/memories/confirm',{'candidates':selected}) if selected else []
    report['checks'].append({'name':'manual_memory_summary_confirm','ok':any(item['value']=='上海' for item in saved),'candidates':candidates,'saved':saved})
    cid2=call('POST','/api/conversations')['id']
    weather,perf=chat(cid2,'我住在哪个城市？请查我所在城市的当前天气，并告诉我数据时间和来源。')
    successful=[item for item in weather.get('tools',[]) if item.get('name')=='weather' and item.get('result',{}).get('ok')]
    report['checks'].append({'name':'cross_session_memory_and_real_weather','ok':'上海' in weather['content'] and bool(successful),'answer':weather['content'],'tools':weather.get('tools',[]),'performance':perf})
    unknown,perf=chat(cid2,'叶瞬光的霜烬剑第七式招式是什么？如果资料没有这个名称就直接说没有依据，别创造新设定。')
    report['checks'].append({'name':'unknown_setting','ok':any(word in unknown['content'] for word in ('没有','未','不','查不到')),'answer':unknown['content'],'sources':unknown.get('sources',[]),'performance':perf})
    search=call('POST','/api/tools/run',{'name':'web_search','args':{'query':'Python programming language','limit':3}})
    report['checks'].append({'name':'real_web_search_english_basic','ok':search.get('ok',False) and bool(search.get('sources')),'result':search})
    for item in saved:call('DELETE','/api/memories/'+item['id'])
    report['checks'].append({'name':'delete_confirmed_facts','ok':call('GET','/api/memories')==[]})
except Exception as error:
    report['checks'].append({'name':'incomplete','ok':False,'error_type':type(error).__name__})
finally:
    client.close()
    target=ROOT/'delivery/integrated-api-report.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'name':item['name'],'ok':item['ok']} for item in report['checks']],ensure_ascii=False,indent=2))
