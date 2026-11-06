"""Real second-provider native Messages SSE + tool roundtrip, no config mutation."""
import asyncio
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage
from backend.app.config import find_saved_config
from backend.app.llm import build_model,extract_text,friendly_error
from backend.app.providers import discover
from backend.app import tools
from backend.app.feature_config import load_features


async def main():
    saved=find_saved_config('https://api.deepseek.com','openai')
    if not saved:raise SystemExit('No saved DeepSeek connection; no call made.')
    config=saved.model_copy(update={'llm_base_url':'https://api.deepseek.com/anthropic','llm_protocol':'anthropic'})
    report={'kind':'real_api','provider':'DeepSeek','protocol':'anthropic','checks':[]}
    try:
        listing=await discover(config)
        report['checks'].append({'name':'models','ok':bool(listing['models']),'models':listing['models']})
        model=build_model(config)
        schema=[s for s in tools.schemas(load_features()) if s['name']=='weather']
        history=[HumanMessage(content='请先调用weather，city="Shanghai", country="CN"查询当前天气，再简短回答气温和时间；不要凭空回答。')]
        start=time.monotonic()
        result=await model.bind_tools(schema).ainvoke(history)
        report['checks'].append({'name':'native_stream_tool_use','ok':bool(result.tool_calls),'tool_names':[c['name'] for c in result.tool_calls],'text':extract_text(result.content)})
        if result.tool_calls:
            history.append(result)
            for call in result.tool_calls[:2]:
                actual=await tools.execute(call['name'],call['args'])
                report['checks'].append({'name':'real_weather','ok':actual.get('ok',False),'result':actual})
                history.append(ToolMessage(content=json.dumps(actual,ensure_ascii=False),tool_call_id=call['id']))
            answer=await model.ainvoke(history)
            report['checks'].append({'name':'native_tool_result_reply','ok':bool(extract_text(answer.content)),'answer':extract_text(answer.content),'total_seconds':round(time.monotonic()-start,3)})
    except Exception as error:
        report['checks'].append({'name':'failure','ok':False,'message':friendly_error(error),'error_type':type(error).__name__})
    target=Path(__file__).resolve().parents[1]/'delivery/deepseek-anthropic-report.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

asyncio.run(main())
