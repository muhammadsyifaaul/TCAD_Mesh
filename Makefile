# ─────────────────────────────────────────────────────────────
# TCAD Mesh — Makefile
# ─────────────────────────────────────────────────────────────
# Make is optional. Raw commands for Windows users are in README.md.
.PHONY: up down test e2e bench demo logs

## Bring all services up, build images, and wait for health
up:
	docker compose up --build -d
	@echo "Waiting for all services to be healthy..."
	@bash scripts/wait-healthy.sh

## Stop and remove containers (volumes preserved)
down:
	docker compose down

## Run unit tests across all services
test:
	@echo "=== gateway ==="
	@MSYS_NO_PATHCONV=1 docker run --rm -v "$$(pwd)/gateway:/src" -w /src golang:1.22-alpine go test ./... -timeout 30s 2>&1 || (echo "=== gateway FAILED ===" && exit 1)
	@echo "=== target-app ==="
	@MSYS_NO_PATHCONV=1 docker run --rm -v "$$(pwd)/target-app:/app" -w /app --entrypoint sh python:3.12-slim -c "pip install -q -r requirements.txt 2>/dev/null && python -m pytest tests/ -q --tb=no 2>&1" || (echo "=== target-app FAILED ===" && exit 1)
	@echo "=== honeypot ==="
	@MSYS_NO_PATHCONV=1 docker run --rm -v "$$(pwd)/honeypot:/app" -w /app --entrypoint sh python:3.12-slim -c "pip install -q -r requirements.txt 2>/dev/null && python -m pytest tests/ -q --tb=no 2>&1" || (echo "=== honeypot FAILED ===" && exit 1)
	@echo "=== control-api (hermetic — no live DB) ==="
	@MSYS_NO_PATHCONV=1 docker run --rm -v "$$(pwd)/control-api:/app" -w /app --entrypoint sh python:3.12-slim -c "pip install -q fastapi==0.111.1 uvicorn httpx==0.27.0 pytest==8.2.2 pytest-asyncio==0.23.7 pydantic==2.7.4 docker==7.1.0 2>/dev/null && python -m pytest tests/ -q --tb=no 2>&1" || (echo "=== control-api FAILED ===" && exit 1)

## Run end-to-end integration tests
e2e:
	bash scripts/e2e.sh

## Run benchmark / metrics harness
bench:
	bash scripts/bench.sh

## Execute the full demo sequence
demo:
	bash scripts/demo.sh

## Tail logs from all services
logs:
	docker compose logs -f
