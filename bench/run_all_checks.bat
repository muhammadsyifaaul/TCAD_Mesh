@echo off
cd /d d:\TCAD_Mesh

echo === BEFORE: live event count ===
docker run --rm --network tcad_mesh_mesh tcad_mesh-bench python -c "import urllib.request,json; r=urllib.request.urlopen('http://control-api:8003/stats',timeout=5); d=json.loads(r.read()); print('events:', d['total_events'])"

echo.
echo === control-api unit tests (hermetic - no network) ===
docker run --rm -v "%CD%\control-api:/app" -v "%CD%\bench\run_ca_tests.sh:/run.sh:ro" -w /app --entrypoint sh python:3.12-slim /run.sh

echo.
echo === AFTER: live event count ===
docker run --rm --network tcad_mesh_mesh tcad_mesh-bench python -c "import urllib.request,json; r=urllib.request.urlopen('http://control-api:8003/stats',timeout=5); d=json.loads(r.read()); print('events:', d['total_events'])"

echo.
echo === dashboard verification ===
docker run --rm --network tcad_mesh_mesh -v "%CD%\bench:/bench:ro" tcad_mesh-bench python /bench/check_dashboard.py
