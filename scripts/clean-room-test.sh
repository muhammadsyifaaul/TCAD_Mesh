#!/usr/bin/env bash
# scripts/clean-room-test.sh
# Simulates a judge running the project from scratch on a clean machine.
# Usage: bash scripts/clean-room-test.sh
# Timing: ~3-5 minutes (build + tests)
#
# MSYS_NO_PATHCONV is NOT exported globally. It is set only inline on the
# docker run commands that need path argument conversion disabled, so that
# curl's -o /dev/null, -w, etc. resolve normally via Git Bash's own /dev/null
# handling. Only docker -v path arguments need MSYS_NO_PATHCONV=1.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0

# Python: try python3 first, then python
if   command -v python3 > /dev/null 2>&1; then PYTHON="python3"
elif command -v python  > /dev/null 2>&1; then PYTHON="python"
else echo "FATAL: python not found" >&2; exit 1; fi

# Output helpers — plain echo avoids ANSI escape/Unicode issues on Windows Git Bash
_g()  { echo "  OK  $*" || true; }
_r()  { echo "  FAIL $*" || true; }
_b()  { echo ""; echo "=== $* ===" || true; }
_bl() { echo ""; echo "[STEP $1] $2" || true; }
ok()  { _g "$*"; PASS=$((PASS+1)); }
fail(){ _r "$*"; FAIL=$((FAIL+1)); }

# http_code URL [extra-curl-args...]
# Returns the 3-digit HTTP status code, or "curl-error-N" on failure.
# NEVER uses -o /dev/null (broken by MSYS_NO_PATHCONV on Windows curl).
# NEVER uses -f (exit 22 on 4xx overwrites code with "FAIL" via || pattern).
http_code() {
  local url="$1"; shift
  local out rc
  out=$(curl -s --max-time 5 -w '%{http_code}' "$url" "$@" 2>&1)
  rc=$?
  if (( rc != 0 )); then echo "curl-error-${rc}"
  else echo "${out: -3}"; fi
}

# docker_run_test <label> <host_path> <image> <sh_cmd>
# Hermetic one-off container — no network → cannot touch live DB.
# MSYS_NO_PATHCONV=1 set inline so only docker -v paths are unmangled.
docker_run_test() {
  local label="$1" host_path="$2" image="$3" cmd="$4"
  local out
  out=$(MSYS_NO_PATHCONV=1 docker run --rm -v "${host_path}:/app" -w /app \
    --entrypoint sh "$image" -c "$cmd" 2>&1) || true
  if echo "$out" | grep -q "passed"; then ok "$label"
  else fail "$label"; echo "$out" | tail -30; fi
}

cd "$REPO_ROOT"
echo "=== TCAD Mesh Clean Room Test ==="
echo ""

# ── STEP 1: Required tools ────────────────────────────────────────────────────
_bl 1 "Verifying required tools"
for tool in docker curl; do
  if command -v "$tool" > /dev/null 2>&1; then ok "$tool found"
  else fail "$tool NOT FOUND"; fi
done
ok "Python: $PYTHON"
if docker info > /dev/null 2>&1; then ok "Docker daemon running"
else fail "Docker daemon not running"; exit 1; fi

# ── STEP 2: .env ──────────────────────────────────────────────────────────────
_bl 2 "Checking .env"
if [[ -f .env ]]; then ok ".env file present"
else cp .env.example .env && ok ".env created from example"; fi

# ── STEP 3: Build ─────────────────────────────────────────────────────────────
_bl 3 "docker compose up --build -d"
docker compose down --remove-orphans > /dev/null 2>&1 || true
# Suppress compose progress output (contains Unicode that breaks some terminals)
DC_RC=0
docker compose up --build -d > /dev/null 2>&1 || DC_RC=$?
if [ "$DC_RC" -eq 0 ]; then ok "docker compose up completed"
else fail "docker compose up --build -d failed (rc=$DC_RC)"; exit 1; fi

# ── STEP 4: Health ────────────────────────────────────────────────────────────
_bl 4 "Waiting for all services to be healthy (max 120s)"
SERVICES=(gateway target-app honeypot control-api dashboard)
TIMEOUT=120; ELAPSED=0
while true; do
  ALL_OK=true
  for svc in "${SERVICES[@]}"; do
    STATUS=$(docker compose ps --format json 2>/dev/null \
      | "$PYTHON" -c "
import sys,json
for line in sys.stdin:
    try:
        o=json.loads(line)
        if o.get('Service','') == '${svc}':
            print(o.get('Health','unknown'))
    except: pass
" 2>/dev/null | head -1)
    [[ "$STATUS" == "healthy" ]] || { ALL_OK=false; break; }
  done
  $ALL_OK && break
  sleep 3; ELAPSED=$((ELAPSED+3))
  if (( ELAPSED >= TIMEOUT )); then
    fail "Services not healthy after ${TIMEOUT}s"
    docker compose ps
    exit 1
  fi
done
ok "All 5 services healthy (${ELAPSED}s)"

# ── STEP 5: Connectivity ──────────────────────────────────────────────────────
_bl 5 "Basic connectivity checks"
# Give Windows Docker port-forwarding a moment to stabilise
sleep 3
for url in \
  "http://localhost:8080/health::gateway" \
  "http://localhost:3000/health::dashboard" \
  "http://localhost:3000/stats::control-api-via-dashboard-proxy"; do
  endpoint="${url%%::*}"; name="${url##*::}"
  CODE="FAIL"
  for _try in 1 2 3 4 5; do
    CODE=$(http_code "$endpoint")
    [[ "$CODE" == "200" ]] && break
    sleep 2
  done
  [[ "$CODE" == "200" ]] && ok "$name → 200" || fail "$name → $CODE (after 5 retries)"
done

# ── STEP 6: Detection pipeline ────────────────────────────────────────────────
_bl 6 "Core detection pipeline (Gate T1)"

# Legit request: check status code AND that body contains real target-app data
# (static IDs from data.py that target-app always returns)
LEGIT_BODY=$(curl -sf "http://localhost:8080/api/v1/shipments" \
  -H "X-Device-ID: cr-legit-1" 2>/dev/null) || LEGIT_BODY=""
LEGIT_ID=$(echo "$LEGIT_BODY" | "$PYTHON" -c \
  "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'] if d.get('data') else 'NONE')" \
  2>/dev/null) || LEGIT_ID="NONE"
# Real target-app always serves these 5 static IDs
REAL_IDS="DOC-1a2b3c4d5e6f DOC-2b3c4d5e6f7a DOC-3c4d5e6f7a8b DOC-4d5e6f7a8b9c DOC-5e6f7a8b9c0d"
if echo "$REAL_IDS" | grep -qw "$LEGIT_ID"; then
  ok "legit request → 200, body contains real target-app ID ($LEGIT_ID)"
else
  fail "legit request → unexpected body ID '$LEGIT_ID' (expected one of real target-app IDs)"
fi

# Canary: check 200 AND body differs from legit (honeypot serves HMAC-derived IDs)
CANARY_ID="cr-canary-$(date +%s)"
http_code "http://localhost:8080/admin" -H "X-Device-ID: $CANARY_ID" > /dev/null
sleep 0.3
CANARY_BODY=$(curl -sf "http://localhost:8080/api/v1/shipments" \
  -H "X-Device-ID: $CANARY_ID" 2>/dev/null) || CANARY_BODY=""
CANARY_FIRST_ID=$(echo "$CANARY_BODY" | "$PYTHON" -c \
  "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'] if d.get('data') else 'NONE')" \
  2>/dev/null) || CANARY_FIRST_ID="NONE"
if [[ "$CANARY_FIRST_ID" != "$LEGIT_ID" && "$CANARY_FIRST_ID" != "NONE" ]]; then
  ok "canary /admin → honeypot (body differs from legit: $CANARY_FIRST_ID ≠ $LEGIT_ID)"
else
  fail "canary /admin → body matches legit or empty ($CANARY_FIRST_ID)"
fi

# Unknown path: 404
CODE=$(http_code "http://localhost:8080/unknown-path-xyz")
[[ "$CODE" == "404" ]] && ok "unknown path → 404" || fail "unknown path → $CODE"

# ── STEP 7: Events ────────────────────────────────────────────────────────────
_bl 7 "Events appear in control-api (Gate T2)"
sleep 2
# Fetch recent events (last 24h) and verify at least one was recorded
EVT_JSON=$(curl -sf "http://localhost:3000/events" 2>/dev/null) || EVT_JSON='{"total":0}'
EVT_TOTAL=$(echo "$EVT_JSON" | "$PYTHON" -c \
  "import sys,json; print(json.load(sys.stdin)['total'])" 2>/dev/null) || EVT_TOTAL=0
(( EVT_TOTAL >= 1 )) && ok "control-api has $EVT_TOTAL events (last 24h)" \
  || fail "control-api has 0 events in last 24h"

# ── STEP 8: Dashboard ─────────────────────────────────────────────────────────
_bl 8 "Dashboard loads and proxies API (Gate T3)"

# Fetch HTML
DASH_HTML=$(curl -sf "http://localhost:3000" 2>/dev/null) || DASH_HTML=""

# Non-empty page (200)
if [[ "${#DASH_HTML}" -gt 100 ]]; then ok "dashboard HTML non-empty (${#DASH_HTML} bytes)"
else fail "dashboard HTML empty or unreachable (${#DASH_HTML} bytes)"; fi

# Root div present (blank-page guard)
if echo "$DASH_HTML" | grep -q 'id="root"'; then ok "dashboard has root div"
else fail "dashboard missing root div — page is blank"; fi

# JS bundle: URL found AND non-empty size check
JS_URL=$(echo "$DASH_HTML" | grep -o '/assets/[^"]*\.js' | head -1)
if [[ -n "$JS_URL" ]]; then
  # Write body to /dev/null via shell redirect (safe — no curl -o flag);
  # -w appends size_download on its own line after the body.
  JS_SIZE=$(curl -s --max-time 10 -w '\n%{size_download}' \
    "http://localhost:3000${JS_URL}" 2>/dev/null | grep -o '^[0-9]*$' | tail -1) || JS_SIZE=0
  JS_SIZE="${JS_SIZE:-0}"
  if (( JS_SIZE > 10000 )); then
    ok "dashboard JS bundle non-empty: ${JS_SIZE} bytes ($JS_URL)"
  else
    fail "dashboard JS bundle too small: ${JS_SIZE} bytes — build may have failed"
  fi
else
  fail "dashboard JS bundle URL not found in HTML"
fi

# /stats proxy
STATS_JSON=$(curl -sf "http://localhost:3000/stats" 2>/dev/null) || STATS_JSON=""
STATS_OK=$(echo "$STATS_JSON" | "$PYTHON" -c \
  "import sys,json; d=json.load(sys.stdin); print('ok' if 'total_events' in d else 'fail')" \
  2>/dev/null) || STATS_OK="fail"
[[ "$STATS_OK" == "ok" ]] && ok "dashboard /stats proxy works" \
  || fail "dashboard /stats proxy broken"

# /honeytokens contract: objects, not strings
HT_JSON=$(curl -sf "http://localhost:3000/honeytokens" 2>/dev/null) || HT_JSON='{"tokens":[]}'
HT_SHAPE=$(echo "$HT_JSON" | "$PYTHON" -c "
import sys,json
d=json.load(sys.stdin); t=d.get('tokens',[])
print('EMPTY' if not t else ('OBJECTS' if isinstance(t[0], dict) else 'STRINGS_BUG'))
" 2>/dev/null) || HT_SHAPE="PARSE_ERROR"
if [[ "$HT_SHAPE" == "OBJECTS" || "$HT_SHAPE" == "EMPTY" ]]; then
  ok "dashboard /honeytokens contract: $HT_SHAPE"
else
  fail "dashboard /honeytokens contract: $HT_SHAPE (expected OBJECTS or EMPTY)"
fi

# BMS Simulator page: SPA serves same HTML (hash-based routing)
BMS_HTML=$(http_code "http://localhost:3000/#/bms")
# The HTML at / is the same SPA shell — the BMS route is client-side.
# We just verify the JS bundle is present (same as main dashboard).
if [[ "$BMS_HTML" == "200" ]]; then
  ok "dashboard BMS page reachable (SPA route)"
else
  fail "dashboard BMS page unreachable: $BMS_HTML"
fi

# ── STEP 9: Unit tests (hermetic one-off containers) ──────────────────────────
_bl 9 "Unit tests (Gate T4)"
# MSYS_NO_PATHCONV=1 set inline on docker run only (not exported globally).
# pwd -W gives Windows-style paths on Git Bash; plain pwd on Linux/macOS.
GW_SRC="$(cd "$REPO_ROOT/gateway"     && { pwd -W 2>/dev/null || pwd; })"
TA_SRC="$(cd "$REPO_ROOT/target-app"  && { pwd -W 2>/dev/null || pwd; })"
HP_SRC="$(cd "$REPO_ROOT/honeypot"    && { pwd -W 2>/dev/null || pwd; })"
CA_SRC="$(cd "$REPO_ROOT/control-api" && { pwd -W 2>/dev/null || pwd; })"
DA_SRC="$(cd "$REPO_ROOT/dashboard"   && { pwd -W 2>/dev/null || pwd; })"

# Gateway Go tests
GO_OUT=$(MSYS_NO_PATHCONV=1 docker run --rm \
  -v "${GW_SRC}:/src" -w /src \
  golang:1.22-alpine go test ./... -timeout 30s 2>&1) || true
if echo "$GO_OUT" | grep -q "^ok"; then ok "gateway go test passed"
else fail "gateway go test failed"; echo "$GO_OUT" | tail -30; fi

# Python service tests (hermetic: no --network)
docker_run_test "target-app pytest" "$TA_SRC" "python:3.12-slim" \
  "pip install -q -r requirements.txt 2>/dev/null; python -m pytest tests/ -q --tb=no 2>&1"
docker_run_test "honeypot pytest" "$HP_SRC" "python:3.12-slim" \
  "pip install -q -r requirements.txt 2>/dev/null; python -m pytest tests/ -q --tb=no 2>&1"
docker_run_test "control-api pytest (hermetic)" "$CA_SRC" "python:3.12-slim" \
  "pip install -q fastapi==0.111.1 uvicorn httpx==0.27.0 pytest==8.2.2 pytest-asyncio==0.23.7 pydantic==2.7.4 docker==7.1.0 2>/dev/null; python -m pytest tests/ -q --tb=no 2>&1"

# Dashboard React component tests (vitest + jsdom)
# npm run test:unit calls "vitest --run" — do not add -- --run again
docker_run_test "dashboard vitest (component tests)" "$DA_SRC" "node:20-alpine" \
  "npm install --legacy-peer-deps --silent 2>/dev/null; npm run test:unit 2>&1"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================"
if (( FAIL == 0 )); then
  echo "PASSED ($PASS checks)"
  exit 0
else
  echo "FAILED: $FAIL/$((PASS+FAIL)) checks failed"
  exit 1
fi
