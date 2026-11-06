"""Small real-service acceptance in isolated QA; never prints credentials."""
import argparse
import json
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--after-restart', action='store_true')
args = parser.parse_args()
target = ROOT / 'delivery/runtime-report.json'
client = httpx.Client(base_url='http://127.0.0.1:8002', timeout=180)

def call(method, path, body=None):
    response = client.request(method, path, json=body)
    response.raise_for_status()
    return response.json()

def stream(cid, text, stop_at_first=False):
    started = time.monotonic()
    first = None
    events = []
    kind = ''
    with client.stream('POST', '/api/chat', json={'conversation_id':cid, 'content':text}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith('event: '): kind = line[7:]
            if line.startswith('data: '):
                data = json.loads(line[6:]); events.append((kind, data))
                if kind == 'delta' and first is None:
                    first = time.monotonic() - started
                    if stop_at_first:
                        call('POST', '/api/chat/'+cid+'/stop')
    done = next((d for k,d in reversed(events) if k == 'done'), None)
    if done is None: raise RuntimeError('No terminal stream event')
    return done, {'first_text_seconds':round(first or 0,3),'total_seconds':round(time.monotonic()-started,3),'delta_events':sum(k=='delta' for k,d in events)}

try:
    if args.after_restart:
        report = json.loads(target.read_text(encoding='utf-8'))
        check = report['stop_record']
        history = call('GET', '/api/conversations/'+check['conversation_id']+'/messages')
        persisted = next(m for m in history if m['id'] == check['message_id'])
        report['checks'].append({'name':'partial_stop_survives_service_restart','ok':persisted['status']=='interrupted' and persisted['content']==check['content']})
        facts = call('GET','/api/memories')
        report['checks'].append({'name':'edited_memory_survives_restart','ok':any(m['value']=='茉莉茶（验收测试）' for m in facts)})
        # Only the two explicitly created acceptance facts are removed.
        for m in facts:
            if (m['key']=='城市' and m['value']=='上海') or m['value']=='茉莉茶（验收测试）':
                call('DELETE','/api/memories/'+m['id'])
        remaining = call('GET','/api/memories')
        report['checks'].append({'name':'test_fact_removal','ok':not any(m['value'] in ('上海','茉莉茶（验收测试）') for m in remaining)})
    else:
        report = {'kind':'real_runtime_acceptance','synthetic_data_only':True,'checks':[]}
        cid = call('POST','/api/conversations')['id']
        stopped, perf = stream(cid,'请写六段约600字的通用散步小故事，不涉及角色设定，不调用工具。这是流式停止测试。',True)
        report['checks'].append({'name':'real_first_delta_then_stop','ok':stopped['status']=='interrupted' and bool(stopped['content']),'performance':perf,'characters_retained':len(stopped['content'])})
        report['stop_record']={'conversation_id':cid,'message_id':stopped['id'],'content':stopped['content']}
        search_cid = call('POST','/api/conversations')['id']
        result, perf = stream(search_cid,'请调用网页搜索查上海博物馆东馆的官网和地址，简短回答并附可打开的来源。')
        calls = [t for t in result.get('tools',[]) if t.get('name')=='web_search' and t.get('result',{}).get('ok')]
        sources = [s for t in calls for s in t['result'].get('sources',[])]
        report['checks'].append({'name':'real_chinese_search_agent_roundtrip','ok':bool(calls) and any('shanghaimuseum' in s.get('url','') for s in sources),'answer':result['content'],'tools':result.get('tools',[]),'performance':perf})
        public = {'kind':'real_public_search','no_api_key':True,'checks':[report['checks'][-1]],'browser_check':{'query':'上海博物馆东馆官网地址','engine':'DuckDuckGo HTML','source_links_openable':True,'width':320},'limits':'Public HTML/RSS is best effort; validation pages are not bypassed. Tavily returned 401 and is optional.'}
        (ROOT/'delivery/public-search-report.json').write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'name':c['name'],'ok':c['ok']} for c in report['checks']],ensure_ascii=False))
finally:
    client.close()
