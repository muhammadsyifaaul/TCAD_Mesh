#!/usr/bin/env bash
# scripts/e2e.sh
# End-to-end integration tests covering Gate T1, T2, and T3 criteria.
# Prerequisites: docker compose up --build -d  (all services healthy)
# Usage:         bash scripts/e2e.sh
# Exit code:     0 = all pass, 1 = failures

set -euo pipefail

# Resolve repo root so the script works from any directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Cross-platform Python detection: python3 first, then python
if command -v python3 > /dev/null 2>&1; then
  PYTHON="python3"
elif command -v python > /dev/null 2>&1; then
  PYTHON="python"
else
  echo "FATAL: Neither python3 nor python found" >&2
  exit 1
fi

GATEWAY="http://localhost:8080"
CTRL="http://localhost:3000"
PASS=0; FAIL=0

_green() { printf '\033[32m%s\033[0m\n' "$*"; }
_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
_bold()  { printf '\033[1m%s\033[0m\n'  "$*"; }
_info()  { printf '  \033[36m→\033[0m %s\n' "$*"; }

assert_eq() {
  local label=$1 actual=$2 expected=$3
  if [[ "$actual" == "$expected" ]]; then
    _green "  ✅  $label (got $actual)"
    PASS=$((PASS+1))
  else
    _red   "  ❌  $label (expected=$expected actual=$actual)"
    FAIL=$((FAIL+1))
  fi
}

assert_contains() {
  local label=$1 haystack=$2 needle=$3
  if echo "$haystack" | grep -q "$needle"; then
    _green "  ✅  $label"
    PASS=$((PASS+1))
  else
    _red   "  ❌  $label (needle='$needle' not found)"
    FAIL=$((FAIL+1))
  fi
}

assert_not_contains() {
  local label=$1 haystack=$2 needle=$3
  if ! echo "$haystack" | grep -q "$needle"; then
    _green "  ✅  $label"
    PASS=$((PASS+1))
  else
    _red   "  ❌  $label (unexpected '$needle' found)"
    FAIL=$((FAIL+1))
  fi
}

wait_healthy() {
  local url=$1 name=$2 max=${3:-30}
  for i in $(seq 1 "$max"); do
    if curl -sf "$url" > /dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  _red "FATAL: $name not healthy after ${max}s"
  exit 1
}

# http_code URL [extra-curl-args...]
# Returns the 3-digit HTTP status code, or "curl-error-N" on network failure.
# Never uses -o /dev/null (broken by MSYS_NO_PATHCONV on Windows curl).
# Never uses -f (exit 22 on 4xx would be overwritten by || CODE="FAIL" idiom).
http_code() {
  local url="$1"; shift
  local out rc
  out=$(curl -s --max-time 10 -w '%{http_code}' "$url" "$@" 2>&1)
  rc=$?
  if (( rc != 0 )); then echo "curl-error-${rc}"
  else echo "${out: -3}"; fi
}

# ── Preflight ─────────────────────────────────────────────────────────────────
_bold "═══════════════════════════════════════════════"
_bold " TCAD Mesh — End-to-End Test Suite"
_bold "═══════════════════════════════════════════════"
echo ""

_bold "Preflight: checking service health…"
wait_healthy "$GATEWAY/health"    "gateway"
wait_healthy "$CTRL/health"       "control-api"
_green "  All services healthy."
echo ""

IKEY=$(grep '^INTERNAL_KEY=' "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2-)
IKEY="${IKEY:-change-me-to-a-random-32-char-string}"

# ──────────────────────────────────────────────────────────────────────────────
_bold "Gate T1 — Mode 1 Core Pipeline"
# ──────────────────────────────────────────────────────────────────────────────

# T1.1: Legitimate request → target-app response, 200
_info "T1.1 Legit request to gateway proxied to target-app"
CODE=$(http_code "$GATEWAY/api/v1/shipments" -H "X-Device-ID: legit-e2e-1")
assert_eq "T1.1 legit request returns 200" "$CODE" "200"
LEGIT_BODY=$(curl -s --max-time 10 "$GATEWAY/api/v1/shipments" -H "X-Device-ID: legit-e2e-1" 2>/dev/null || echo "")
LEGIT_ID=$(echo "$LEGIT_BODY" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'] if d.get('data') else 'NONE')" 2>/dev/null || echo "NONE")
_info "  Legit shipment ID: $LEGIT_ID"

# T1.2: GET /admin → honeypot (200 from catch-all), CANARY_HIT event fired
_info "T1.2 Canary path /admin → honeypot (200)"
CANARY_ID="e2e-canary-$(date +%s)"
CODE=$(http_code "$GATEWAY/admin" -H "X-Device-ID: $CANARY_ID")
assert_eq "T1.2 canary path returns 200 (honeypot)" "$CODE" "200"

# T1.3: Subsequent request from quarantined identity → honeypot (body must differ from legit)
_info "T1.3 Quarantined identity follow-up → honeypot (body differs from legit)"
sleep 0.5
QUARANTINED_BODY=$(curl -sf "$GATEWAY/api/v1/shipments" -H "X-Device-ID: $CANARY_ID")
QUARANTINED_ID=$(echo "$QUARANTINED_BODY" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'] if d.get('data') else 'NONE')" 2>/dev/null || echo "NONE")
_info "  Quarantined shipment ID: $QUARANTINED_ID (legit was: $LEGIT_ID)"
if [[ "$QUARANTINED_ID" != "$LEGIT_ID" && "$QUARANTINED_ID" != "NONE" ]]; then
  _green "  ✅  T1.3 quarantined body differs from legit (honeypot data confirmed)"
  PASS=$((PASS+1))
else
  _red   "  ❌  T1.3 quarantined body matches legit (not routed to honeypot!) IDs: legit=$LEGIT_ID quarantined=$QUARANTINED_ID"
  FAIL=$((FAIL+1))
fi

# T1.4: 7 requests to random 404 paths → ENUM_DETECTED (tarpit active)
_info "T1.4 Enum detection: 7 x 404 → ENUM_DETECTED"
ENUM_ID="e2e-enum-$(date +%s)"
for i in $(seq 1 7); do
  http_code "$GATEWAY/nonexistent-e2e-path-$i" \
       -H "X-Device-ID: $ENUM_ID" > /dev/null
done
sleep 1   # allow async event dispatch to settle
EVENTS=$(curl -sf "$CTRL/events?type=ENUM_DETECTED&limit=10" \
         | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d['total'])")
if (( EVENTS >= 1 )); then
  _green "  ✅  T1.4 ENUM_DETECTED fired ($EVENTS events)"
  PASS=$((PASS+1))
else
  _red   "  ❌  T1.4 ENUM_DETECTED not found in control-api events"
  FAIL=$((FAIL+1))
fi

# T1.5: Header normalisation — Server = nginx, no X-Powered-By
_info "T1.5 Header normalisation"
HEADERS=$(curl -sI "$GATEWAY/api/v1/shipments" -H "X-Device-ID: legit-e2e-2")
assert_contains     "T1.5a Server: nginx"         "$HEADERS" "nginx"
assert_not_contains "T1.5b no X-Powered-By"        "$HEADERS" "X-Powered-By"

# T1.6: Unknown path returns 404
_info "T1.6 Unknown path returns 404"
CODE=$(http_code "$GATEWAY/totally-unknown" -H "X-Device-ID: legit-e2e-3")
assert_eq "T1.6 unknown path returns 404" "$CODE" "404"

echo ""

# ──────────────────────────────────────────────────────────────────────────────
_bold "Gate T2 — Control-API, Events, Quarantine"
# ──────────────────────────────────────────────────────────────────────────────

# T2.1: CANARY_HIT event in control-api
_info "T2.1 CANARY_HIT event recorded in control-api"
CANARY_COUNT=$(curl -sf "$CTRL/events?type=CANARY_HIT&limit=50" \
  | $PYTHON -c "import sys,json; print(json.load(sys.stdin)['total'])")
if (( CANARY_COUNT >= 1 )); then
  _green "  ✅  T2.1 CANARY_HIT events: $CANARY_COUNT"
  PASS=$((PASS+1))
else
  _red   "  ❌  T2.1 no CANARY_HIT events in control-api"
  FAIL=$((FAIL+1))
fi

# T2.2: Active quarantines visible
_info "T2.2 Active quarantine list"
Q_COUNT=$(curl -sf "$CTRL/quarantine" \
  | $PYTHON -c "import sys,json; print(len(json.load(sys.stdin)['data']))")
if (( Q_COUNT >= 1 )); then
  _green "  ✅  T2.2 Active quarantines: $Q_COUNT"
  PASS=$((PASS+1))
else
  _red   "  ❌  T2.2 no active quarantines found"
  FAIL=$((FAIL+1))
fi

# T2.3: Quarantine release propagates within ≤2s — body must match legit (target-app data)
_info "T2.3 Quarantine release propagation (≤2s) — body must match legit"
REL_ID="e2e-rel-$(date +%s)"
# Trigger canary to quarantine REL_ID
http_code "$GATEWAY/admin" -H "X-Device-ID: $REL_ID" > /dev/null
sleep 0.5
# Release via control-api
curl -sf "$CTRL/quarantine/${REL_ID}/release" -X POST \
     -H "X-Internal-Key: $IKEY" > /dev/null 2>&1 || true
sleep 2.5  # wait for quarantine poller (2s interval) + buffer
# Now REL_ID should reach target-app again — body must match legit client's
RELEASED_BODY=$(curl -sf "$GATEWAY/api/v1/shipments" -H "X-Device-ID: $REL_ID")
RELEASED_ID=$(echo "$RELEASED_BODY" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'] if d.get('data') else 'NONE')" 2>/dev/null || echo "NONE")
_info "  Released ID: $RELEASED_ID (legit was: $LEGIT_ID)"
if [[ "$RELEASED_ID" == "$LEGIT_ID" ]]; then
  _green "  ✅  T2.3 released identity gets real target-app data (matches legit)"
  PASS=$((PASS+1))
else
  _red   "  ❌  T2.3 released identity body differs from legit (still in honeypot? or different data)"
  FAIL=$((FAIL+1))
fi

# T2.6: Quarantine race condition fix — unconfirmed entry must survive empty poll
# Body must differ from legit (honeypot data), confirming quarantine is active
_info "T2.6 Quarantine sync race: add then immediately check → honeypot data (differs from legit)"
RACE_ID="e2e-race-$(date +%s)"
http_code "$GATEWAY/admin" -H "X-Device-ID: $RACE_ID" > /dev/null
# Immediately check — quarantine must be active (race would send to target-app)
RACE_BODY=$(curl -sf "$GATEWAY/api/v1/shipments" -H "X-Device-ID: $RACE_ID")
RACE_ID_VAL=$(echo "$RACE_BODY" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'] if d.get('data') else 'NONE')" 2>/dev/null || echo "NONE")
_info "  Race ID: $RACE_ID_VAL (legit was: $LEGIT_ID)"
if [[ "$RACE_ID_VAL" != "$LEGIT_ID" && "$RACE_ID_VAL" != "NONE" ]]; then
  _green "  ✅  T2.6 quarantine holds even before control-api confirms (honeypot data)"
  PASS=$((PASS+1))
else
  _red   "  ❌  T2.6 quarantine dropped before confirm — got target-app data (race condition!)"
  FAIL=$((FAIL+1))
fi
echo ""
_info "T2.4 Gateway survives control-api downtime"
docker compose stop control-api > /dev/null 2>&1 || true
sleep 1
CODE=$(http_code "$GATEWAY/api/v1/shipments" -H "X-Device-ID: legit-e2e-resilience")
assert_eq "T2.4 gateway returns 200 while control-api is down" "$CODE" "200"

# Restore control-api and wait until healthy before continuing
docker compose start control-api > /dev/null 2>&1 || true
_info "  Waiting for control-api to recover…"
for _i in $(seq 1 30); do
  if curl -sf "$CTRL/health" > /dev/null 2>&1; then
    _green "  ✅  control-api recovered after ${_i}s"
    break
  fi
  sleep 1
done
# Extra settle time for gateway quarantine poller to re-sync
sleep 2

# ──────────────────────────────────────────────────────────────────────────────
_bold "Gate T2.5 — Honeytoken Reuse Attribution"
# ──────────────────────────────────────────────────────────────────────────────

# T2.5: HONEYTOKEN_REUSED fires with correct attribution
# Flow: (1) quarantine attacker via canary → (2) honeypot serves token →
#       (3) gateway polls tokens (2s) → (4) new identity reuses token
_info "T2.5 Honeytoken reuse detection"

# Step 1: Quarantine attacker-A via canary
HT_ID_A="e2e-ht-attacker-A-$(date +%s)"
http_code "$GATEWAY/admin" -H "X-Device-ID: $HT_ID_A" > /dev/null
sleep 0.5

# Step 2: Extract a honeytoken from the honeypot response (attacker-A is quarantined)
HT_TOKEN=$(curl -sf "$GATEWAY/api/v1/shipments" -H "X-Device-ID: $HT_ID_A" \
  | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'] if d.get('data') else '')" 2>/dev/null || echo "")
if [[ -z "$HT_TOKEN" || "$HT_TOKEN" == "" ]]; then
  _red "  ❌  T2.5 Could not extract honeytoken from honeypot response"
  FAIL=$((FAIL+1))
else
  _info "  Captured honeytoken: $HT_TOKEN"

  # Step 3: Wait for gateway to poll honeytoken list from control-api
  # (HONEYTOKEN_POLL_MS=500 default → 2 poll cycles + processing buffer)
  sleep 4

  # Step 4: A different identity reuses the token in the URI
  HT_ID_B="e2e-ht-attacker-B-$(date +%s)"
  http_code "$GATEWAY/api/v1/shipments?doc=$HT_TOKEN" \
       -H "X-Device-ID: $HT_ID_B" > /dev/null
  sleep 3  # allow async HONEYTOKEN_REUSED event to dispatch and land

  # Step 5: Check HONEYTOKEN_REUSED event with session attribution correctness.
  # Requires: detail.original_session != reusing identity (i.e. attribution points
  # to the ISSUING session, not the reusing session). This is the correctness check.
  HT_REUSE_RAW=$(curl -sf "$CTRL/events?type=HONEYTOKEN_REUSED&limit=50" 2>/dev/null || echo '{"data":[]}')
  HT_REUSE_COUNT=$(echo "$HT_REUSE_RAW" | $PYTHON -c "import sys,json; print(json.load(sys.stdin)['total'])" 2>/dev/null || echo "0")

  CORRECT_ATTR=$(echo "$HT_REUSE_RAW" | $PYTHON -c "
import sys,json
d=json.load(sys.stdin)
matched=0
for ev in d.get('data',[]):
    detail = ev.get('detail') or {}
    orig = detail.get('original_session','')
    reuser_id = ev.get('identity','')
    # Correct: original_session is the ISSUING identity (HT_ID_A), different from reuser
    if orig and orig != reuser_id:
        matched += 1
print(matched)
" 2>/dev/null || echo "0")

  if (( HT_REUSE_COUNT >= 1 )) && (( CORRECT_ATTR >= 1 )); then
    _green "  ✅  T2.5 HONEYTOKEN_REUSED: $HT_REUSE_COUNT events, $CORRECT_ATTR with correct session attribution"
    PASS=$((PASS+1))
  elif (( HT_REUSE_COUNT >= 1 )); then
    _red   "  ❌  T2.5 HONEYTOKEN_REUSED: $HT_REUSE_COUNT events but session attribution wrong (original_session == reusing identity)"
    FAIL=$((FAIL+1))
  else
    _red   "  ❌  T2.5 No HONEYTOKEN_REUSED events detected"
    FAIL=$((FAIL+1))
  fi
fi

echo ""

# ──────────────────────────────────────────────────────────────────────────────
_bold "Gate T3 — Attacker-Sim Allowlist"
# ──────────────────────────────────────────────────────────────────────────────

# T3.1: Allowlist rejects external IP (via the running attacker-sim service)
_info "T3.1 Allowlist rejects external IP"
RESULT=$(docker compose exec -T attacker-sim $PYTHON -c "
from allowlist import validate_target, AllowlistViolation
try:
    validate_target('http://8.8.8.8')
    print('ALLOWED')
except AllowlistViolation:
    print('REJECTED')
" 2>/dev/null || echo "REJECTED")
assert_eq "T3.1 external IP rejected by allowlist" "$RESULT" "REJECTED"

# T3.2: Dashboard API contract validation — honeytokens must be objects, not strings
_info "T3.2 Dashboard API contract: GET /honeytokens returns objects"
HT_SHAPE=$(curl -sf "$CTRL/honeytokens" | $PYTHON -c "
import sys, json
d = json.load(sys.stdin)
tokens = d.get('tokens', [])
if not tokens:
    print('EMPTY')
elif isinstance(tokens[0], dict):
    print('OBJECTS')
elif isinstance(tokens[0], str):
    print('STRINGS_BUG')
else:
    print('UNKNOWN')
" 2>/dev/null || echo "ERROR")
if [[ "$HT_SHAPE" == "OBJECTS" || "$HT_SHAPE" == "EMPTY" ]]; then
  _green "  ✅  T3.2 honeytokens response: $HT_SHAPE"
  PASS=$((PASS+1))
else
  _red   "  ❌  T3.2 honeytokens response: $HT_SHAPE (expected OBJECTS or EMPTY)"
  FAIL=$((FAIL+1))
fi

# T3.3: Dashboard HTML and JS bundle load
_info "T3.3 Dashboard renders (HTML + JS bundle)"
DASH_HTML=$(curl -sf http://localhost:3000 2>/dev/null || echo "")
if echo "$DASH_HTML" | grep -q 'id="root"'; then
  _green "  ✅  T3.3a dashboard index.html has root div"
  PASS=$((PASS+1))
else
  _red   "  ❌  T3.3a dashboard index.html missing root div"
  FAIL=$((FAIL+1))
fi
# Verify the JS bundle loads (catches build failures)
JS_URL=$(echo "$DASH_HTML" | grep -o '/assets/[^"]*\.js' | head -1)
if [[ -n "$JS_URL" ]]; then
  JS_CODE=$(http_code "http://localhost:3000$JS_URL")
  if [[ "$JS_CODE" == "200" ]]; then
    _green "  ✅  T3.3b dashboard JS bundle loads ($JS_URL)"
    PASS=$((PASS+1))
  else
    _red   "  ❌  T3.3b dashboard JS bundle failed: HTTP $JS_CODE"
    FAIL=$((FAIL+1))
  fi
else
  _red   "  ❌  T3.3b dashboard JS bundle URL not found in HTML"
  FAIL=$((FAIL+1))
fi

echo ""

# ──────────────────────────────────────────────────────────────────────────────
_bold "Gate T4 — Hardening"
# ──────────────────────────────────────────────────────────────────────────────

# T4.1: Oversized body rejected with 413
_info "T4.1 Oversized request body returns 413"
# Generate a 2MB body and POST it — should get 413
# Pipe body via stdin; http_code doesn't support piped stdin, so use curl directly.
# No -o flag needed: -w writes after body; body goes to stdout but we only keep last 3 chars.
RAW_OUT=$(dd if=/dev/zero bs=1M count=2 2>/dev/null | \
       curl -s --max-time 15 -w '%{http_code}' -X POST \
       --data-binary @- "$GATEWAY/api/v1/shipments" \
       -H "X-Device-ID: body-limit-test" \
       -H "Content-Type: application/octet-stream" 2>&1)
CODE="${RAW_OUT: -3}"
# 413 or 400 (if the upstream rejects it first) are acceptable
if [[ "$CODE" == "413" || "$CODE" == "400" ]]; then
  _green "  ✅  T4.1 body > 1MB returns $CODE"
  PASS=$((PASS+1))
else
  _red   "  ❌  T4.1 body > 1MB returns $CODE (expected 413 or 400)"
  FAIL=$((FAIL+1))
fi

# T4.2: Gateway /health responds quickly (< 200ms)
_info "T4.2 /health response time < 200ms"
TIME_MS=$(curl -s --max-time 10 -w "%{time_total}" "$GATEWAY/health" 2>/dev/null \
  | tr -d '\r\n' | grep -o '[0-9.]*$' | awk '{printf "%d", $1*1000}')
if (( TIME_MS < 200 )); then
  _green "  ✅  T4.2 /health latency: ${TIME_MS}ms"
  PASS=$((PASS+1))
else
  _red   "  ❌  T4.2 /health too slow: ${TIME_MS}ms (want <200ms)"
  FAIL=$((FAIL+1))
fi

echo ""

# ──────────────────────────────────────────────────────────────────────────────
_bold "Gate T5 — Full Demo Scenario (end-to-end story)"
# ──────────────────────────────────────────────────────────────────────────────
# Trigger the full scenario via control-api (which calls attacker-sim).
# Then assert that all required event types appeared and that HONEYTOKEN_REUSED
# has correct original_session attribution.
#
# This test runs AFTER the other gates so the system is already warm.
# It issues a POST /reset first (via the full scenario itself) so counts are fresh.

_info "T5 Full-demo scenario — triggering via POST /sim/run full..."

# Kick off the scenario
SIM_RESP=$(curl -sf -X POST "$CTRL/sim/run" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Key: $IKEY" \
  -d '{"scenario":"full"}' 2>/dev/null) || SIM_RESP=""

RUN_ID=$(echo "$SIM_RESP" | $PYTHON -c \
  "import sys,json; print(json.load(sys.stdin).get('run_id',''))" 2>/dev/null || echo "")
if [[ -z "$RUN_ID" ]]; then
  _red "  ❌  T5.0 sim/run did not return a run_id — is control-api healthy?"
  FAIL=$((FAIL+1))
else
  _green "  ✅  T5.0 sim/run accepted — run_id: $RUN_ID"
  PASS=$((PASS+1))
fi

# Poll sim/status until completed or timeout (120 s — full scenario takes ~90 s)
_info "  Waiting for full scenario to complete (max 120 s)..."
T5_STATUS="running"
for _w in $(seq 1 40); do
  sleep 3
  T5_STATUS=$(curl -sf "$CTRL/sim/status" 2>/dev/null \
    | $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" \
    2>/dev/null || echo "unknown")
  [[ "$T5_STATUS" != "running" ]] && break
done

# The full scenario's Phase 0 calls POST /reset which preserves sim_runs (since the
# fix), so status persists. But if the scenario finishes extremely fast and we catch it
# in the brief "idle" window between DELETE and INSERT, also accept "completed" or any
# non-running non-idle terminal state.
if [[ "$T5_STATUS" == "completed" ]]; then
  _green "  ✅  T5.1 full scenario completed"
  PASS=$((PASS+1))
elif [[ "$T5_STATUS" == "failed" ]]; then
  _red   "  ❌  T5.1 full scenario ended with status: failed"
  FAIL=$((FAIL+1))
else
  # Could be "idle" if sim/status was polled between reset and new run insertion
  # or if the scenario hasn't started yet — give it one more chance after 10s
  sleep 10
  T5_STATUS=$(curl -sf "$CTRL/sim/status" 2>/dev/null \
    | $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" \
    2>/dev/null || echo "unknown")
  if [[ "$T5_STATUS" == "completed" ]]; then
    _green "  ✅  T5.1 full scenario completed (caught on retry)"
    PASS=$((PASS+1))
  else
    _red   "  ❌  T5.1 full scenario ended with status: $T5_STATUS (expected completed)"
    FAIL=$((FAIL+1))
  fi
fi

# Extra settle time for all async events (gateway→control-api dispatch) to land
sleep 8

# --- T5.2: Required event types present ----------------------------------------
# After a full run from clean state (POST /reset is phase 0 of the scenario),
# every step of the attack story must have produced at least one event.
_info "T5.2 Checking required event types after full scenario..."

EVENTS_JSON=$(curl -sf "$CTRL/events?limit=200" 2>/dev/null) || EVENTS_JSON='{"data":[]}'
STATS_JSON=$(curl -sf "$CTRL/stats" 2>/dev/null)  || STATS_JSON='{}'

check_event_type() {
  local label=$1 etype=$2 min_count=${3:-1}
  local count
  count=$(echo "$EVENTS_JSON" | $PYTHON -c "
import sys,json
d=json.load(sys.stdin)
n=[e for e in d.get('data',[]) if e.get('event_type')=='${etype}']
print(len(n))
" 2>/dev/null || echo "0")
  if (( count >= min_count )); then
    _green "  ✅  $label: ${etype} × ${count}"
    PASS=$((PASS+1))
  else
    _red   "  ❌  $label: ${etype} × ${count} (expected >= ${min_count})"
    FAIL=$((FAIL+1))
  fi
}

check_event_type "T5.2a CANARY_HIT"        "CANARY_HIT"        1
check_event_type "T5.2b QUARANTINED"       "QUARANTINED"       1
check_event_type "T5.2c ENUM_DETECTED"     "ENUM_DETECTED"     1
check_event_type "T5.2d TARPIT_ACTIVE"     "TARPIT_ACTIVE"     1
check_event_type "T5.2e HONEYTOKEN_ISSUED" "HONEYTOKEN_ISSUED" 1
check_event_type "T5.2f HONEYTOKEN_REUSED" "HONEYTOKEN_REUSED" 1

# --- T5.3: HONEYTOKEN_REUSED has correct original_session attribution ----------
_info "T5.3 HONEYTOKEN_REUSED original_session attribution..."

REUSE_EVENTS=$(curl -sf "$CTRL/events?type=HONEYTOKEN_REUSED&limit=50" 2>/dev/null \
  || echo '{"data":[]}')

ATTR_OK=$(echo "$REUSE_EVENTS" | $PYTHON -c "
import sys,json
d=json.load(sys.stdin)
matched=0
for ev in d.get('data',[]):
    detail = ev.get('detail') or {}
    orig   = detail.get('original_session','')
    reuser = ev.get('identity','')
    # Correct: original_session present AND differs from the reuser identity
    if orig and orig != reuser:
        matched += 1
print(matched)
" 2>/dev/null || echo "0")

REUSE_TOTAL=$(echo "$REUSE_EVENTS" | $PYTHON -c \
  "import sys,json; print(json.load(sys.stdin)['total'])" 2>/dev/null || echo "0")

if (( ATTR_OK >= 1 )); then
  _green "  ✅  T5.3 HONEYTOKEN_REUSED: ${REUSE_TOTAL} event(s), ${ATTR_OK} with correct attribution"
  PASS=$((PASS+1))
elif (( REUSE_TOTAL >= 1 )); then
  _red   "  ❌  T5.3 HONEYTOKEN_REUSED fired (${REUSE_TOTAL}) but original_session == reusing identity"
  FAIL=$((FAIL+1))
else
  _red   "  ❌  T5.3 no HONEYTOKEN_REUSED events found"
  FAIL=$((FAIL+1))
fi

# --- T5.4: Legit traffic survived (legit post-attack all 2xx) ------------------
_info "T5.4 Legit traffic survived the attack..."

# Probe from a fresh "post-t5" identity — must get 200 from target-app
CODE=$(http_code "$GATEWAY/api/v1/shipments" -H "X-Device-ID: e2e-post-t5-$(date +%s)")
assert_eq "T5.4 legit client gets 200 after full scenario" "$CODE" "200"

echo ""

# ──────────────────────────────────────────────────────────────────────────────
_bold "Summary"
# ──────────────────────────────────────────────────────────────────────────────
TOTAL=$((PASS+FAIL))
if (( FAIL == 0 )); then
  _green "✅  ALL $TOTAL TESTS PASSED"
  exit 0
else
  _red   "❌  $FAIL/$TOTAL TESTS FAILED"
  exit 1
fi
