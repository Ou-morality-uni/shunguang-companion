"""Explicit storage/port options for isolated verification, not model configuration."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
parser=argparse.ArgumentParser()
parser.add_argument('--data-dir', type=Path)
parser.add_argument('--port',type=int,default=8000)
parser.add_argument('--host',default='127.0.0.1')
args=parser.parse_args()
from backend.app import config
if args.data_dir:
    config.DATA_DIR=args.data_dir.resolve()
from backend.app.main import app
import uvicorn
uvicorn.run(app,host=args.host,port=args.port,access_log=False)
