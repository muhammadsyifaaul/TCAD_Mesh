#!/usr/bin/env bash
# scripts/test-resilience.sh
# Gate T2 — Live Docker resilience test:
#   Proves that killing control-api does NOT crash or significantly slow gateway.
#
# Prerequisites: docker compose up --build -d  (all services healthy)
# Usage:         bash scripts/test-resilience.sh
#
# Exit code: 0 = PASS, 1 = FAIL

set -euo pipefail

GATEWAY="http://localhost:8080"
CTRL="http://localhost:3000"   # Dashboard proxy forwards to control-api
N=20                           # requests per phase
MAX_LATENCY_MS=2000            # phase 2 per-request wall-time ceiling (ms)
PASS=0; FAIL=0

_green() { echo -e "\033[32m$*\033[0m"; }
_red()   { echo -e "\033[31m$*\033[0m"; }
_bold()  { echo -e "\033[1m$*\033[0m"; }

check() {
  local label=$1 actual=$2 limit=$3
  if (( actual <= limit )); then
    _green "  ✅  $label: ${actual}ms ≤ ${limit}ms"
    PASS=$((PASS+1))
  else
    _red   "  ❌  $label: ${actual}ms > ${limit}ms"
    FAIL=$((FAIL+1))
  fi
}

# ── Measure median latency for N sequential requests ─────────────────────────
# Returns the median ms as an integer to stdout.
measure_median_ms() {
  local path=$1
  local times=()
  for i in $(seq 1 "$N"); do
    local ms
    ms=$(curl -s -o /dev/null -w "%{time_total}" "${GATEWAY}${path}" \
         -H "X-Device-ID: test-device-$RANDOM" 2>/dev/null \
         | awk '{printf "%d", $1 * 1000}')
    times+=("$ms")
  done
  # Sort and pick median
  IFS=$'\n' sorted=($(sort -n <<<"${times[*]}")); unset IFS
  echo "${sorted[$((N/2))]}"
}

_bold "═══════════════════════════════════════════════════"
_bold " TCAD Mesh — Gate T2 Resilience Test"
_bold "═══════════════════════════════════════════════════"
echo ""

# ── Preflight: gateway must be up ─────────────────────────────────────────────
echo "→ Checking gateway health..."
if ! curl -sf "${GATEWAY}/health" > /dev/null; then
  _red "FATAL: gateway is not reachable at ${GATEWAY}. Run 'docker compose up -d' first."
  exit 1
fi
_green "  Gateway is healthy."
echo ""

# ── Phase 1: control-api UP ───────────────────────────────────────────────────
_bold "Phase 1 — control-api UP (baseline)"
med1=$(measure_median_ms "/api/v1/shipments")
echo "  Median latency: ${med1}ms"
echo ""

# ── Kill control-api ──────────────────────────────────────────────────────────
_bold "Stopping control-api container..."
docker compose stop control-api 2>/dev/null || true
sleep 1
echo "  control-api stopped."
echo ""

# ── Phase 2: control-api DOWN ─────────────────────────────────────────────────
_bold "Phase 2 — control-api DOWN (resilience)"
phase2_times=()
phase2_start=$(date +%s%3N)
for i in $(seq 1 "$N"); do
  ms=$(curl -s -o /dev/null -w "%{time_total}" "${GATEWAY}/api/v1/shipments" \
       -H "X-Device-ID: resilience-$RANDOM" 2>/dev/null \
       | awk '{printf "%d", $1 * 1000}')
  phase2_times+=("$ms")
done
phase2_end=$(date +%s%3N)
phase2_wall=$(( phase2_end - phase2_start ))

IFS=$'\n' sorted2=($(sort -n <<<"${phase2_times[*]}")); unset IFS
med2="${sorted2[$((N/2))]}"

echo "  Median latency: ${med2}ms  (wall time for $N requests: ${phase2_wall}ms)"

# Check: no response should have taken longer than MAX_LATENCY_MS
max2=0
for t in "${phase2_times[@]}"; do
  (( t > max2 )) && max2=$t
done
check "max single request during outage" "$max2" "$MAX_LATENCY_MS"

# Check: median must not be more than 3× baseline
limit3x=$(( med1 * 3 ))
if (( limit3x < 100 )); then limit3x=100; fi
check "median latency during outage ≤ 3× baseline" "$med2" "$limit3x"
echo ""

# ── Phase 3: Restart control-api and verify recovery ─────────────────────────
_bold "Phase 3 — control-api restarted (recovery)"
docker compose start control-api 2>/dev/null || true
echo "  Waiting up to 30s for control-api to become healthy again..."
for i in $(seq 1 30); do
  if curl -sf "http://localhost:3000/health" > /dev/null 2>&1; then
    _green "  control-api healthy after ${i}s"
    break
  fi
  sleep 1
done

med3=$(measure_median_ms "/api/v1/shipments")
echo "  Median latency after recovery: ${med3}ms"
check "recovery median ≤ 2× baseline" "$med3" "$(( med1 * 2 < 100 ? 100 : med1 * 2 ))"
echo ""

# ── Canary path still works after recovery ────────────────────────────────────
_bold "Canary path smoke test post-recovery"
# Use a fresh stable device ID so it definitely isn't quarantined yet
SMOKE_ID="smoke-canary-$(date +%s)"
HTTP_CODE=$(curl -s -o /tmp/tcad_smoke_body.json -w "%{http_code}" \
            "${GATEWAY}/admin" \
            -H "X-Device-ID: ${SMOKE_ID}")
BODY=$(cat /tmp/tcad_smoke_body.json 2>/dev/null || echo "")

# Honeypot serves /admin as a catch-all → must return 200
# (The attacker should see a plausible API response, not a 404)
if [[ "$HTTP_CODE" == "200" ]]; then
  _green "  ✅  GET /admin returned 200 (honeypot catch-all working)"
  PASS=$((PASS+1))
else
  _red   "  ❌  GET /admin returned $HTTP_CODE — body: $BODY"
  echo ""
  _red   "  Diagnosis: honeypot may be returning 404 for /admin."
  _red   "  Check: docker compose logs honeypot | tail -20"
  FAIL=$((FAIL+1))
fi

# Second request with same ID must also return 200 (quarantine active → honeypot)
HTTP_CODE2=$(curl -s -o /dev/null -w "%{http_code}" \
             "${GATEWAY}/api/v1/shipments" \
             -H "X-Device-ID: ${SMOKE_ID}")
if [[ "$HTTP_CODE2" == "200" ]]; then
  _green "  ✅  Follow-up request from same quarantined identity returned 200"
  PASS=$((PASS+1))
else
  _red   "  ❌  Follow-up quarantined request returned $HTTP_CODE2 (expected 200)"
  FAIL=$((FAIL+1))
fi
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
_bold "═══════════════════════════════════════════════════"
if (( FAIL == 0 )); then
  _green " ✅  ALL CHECKS PASSED ($PASS/$((PASS+FAIL)))"
  _bold "═══════════════════════════════════════════════════"
  exit 0
else
  _red   " ❌  $FAIL CHECKS FAILED ($PASS/$((PASS+FAIL)) passed)"
  _bold "═══════════════════════════════════════════════════"
  exit 1
fi
