"""Isolated real-API UI server; does not touch private conversation database."""
import shutil
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app import config
qa_dir=config.ROOT/'artifacts/qa/real-data'
qa_dir.mkdir(parents=True,exist_ok=True)
source=config.DATA_DIR/'settings.json'
if source.is_file():
    shutil.copy2(source,qa_dir/'settings.json')
config.DATA_DIR=qa_dir
from backend.app.main import app
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=8002,access_log=False)
