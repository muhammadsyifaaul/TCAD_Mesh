#!/usr/bin/env sh
# Run control-api tests hermetically — no network, no live DB
pip install -q fastapi==0.111.1 uvicorn httpx==0.27.0 pytest==8.2.2 pytest-asyncio==0.23.7 pydantic==2.7.4 docker==7.1.0 2>/dev/null
python -m pytest tests/test_control_api.py -q --tb=short 2>&1
