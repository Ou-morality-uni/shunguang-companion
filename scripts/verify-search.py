"""One real configured Chinese search; output public sources only."""
import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.tools import execute

async def main():
    start=time.monotonic()
    result=await execute('web_search',{'query':'上海博物馆东馆 官网 地址','limit':3})
    report={'kind':'real_api','seconds':round(time.monotonic()-start,3),'result':result}
    target=Path(__file__).resolve().parents[1]/'delivery/chinese-search-report.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
asyncio.run(main())
