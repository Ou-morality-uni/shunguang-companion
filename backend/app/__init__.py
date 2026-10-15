"""Initialize privacy defaults before importing any model SDK."""

import os

os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'
