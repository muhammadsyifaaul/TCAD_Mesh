#!/usr/bin/env sh
# bench/k6-bench/run-open-loop.sh
# Open-loop latency benchmark using k6 constant-arrival-rate.
#
# TRUE open-loop test: k6 constant-arrival-rate executor generates exactly
# N iterations/s regardless of response latency. Closed-loop tools saturate
# at concurrency / latency; this does not.
#
# Rate validation: k6 constant-arrival-rate tracks actual rate precisely.
# A run is marked valid if achieved rate is within 5% of requested.
#
# Usage (from host):
#   docker run --rm --network tcad_mesh_mesh \
#     -v /d/TCAD_Mesh/bench/k6-bench:/bench:ro \
#     -v /d/TCAD_Mesh/results:/out \
#     grafana/k6:latest sh /bench/run-open-loop.sh
#
# Output: /out/bench_openloop.json + stdout

set -eu

# Use /out for results (host-mounted); fall back to /tmp if not available
if [ -w "/out" ]; then
  OUT="/out/bench_openloop.json"
else
  OUT="/tmp/bench_openloop.json"
fi

GATEWAY_URL="http://gateway:8080"
UPSTREAM_URL="http://target-app:8001"
ENDPOINT="/api/v1/shipments"
RATES="50 100 200"
DURATION="60s"
REPS=3

echo "[openloop] k6 constant-arrival-rate open-loop benchmark"
echo "[openloop] Rates: ${RATES} req/s  Duration: ${DURATION}  Reps: ${REPS}"
echo "[openloop] Endpoint: ${ENDPOINT}"
echo ""

# k6 summary output: parse med= for p50 and p(95)= for p95
# k6 --summary-trend-stats lets us add p99 to the output
extract_med() {
  # "http_req_duration...: med=2.97ms p(95)=12.54ms p(99)=22.89ms"
  # grep -o 'med=[0-9.]*' gives "med=2.97", then strip prefix
  echo "$1" | grep "http_req_duration" | grep -v "expected_response" | \
    grep -o 'med=[0-9.]*' | sed 's/med=//' | head -1
}
extract_p95() {
  # p(95)=12.54ms → strip 'p(95)=' prefix to get '12.54'
  echo "$1" | grep "http_req_duration" | grep -v "expected_response" | \
    grep -o 'p(95)=[0-9.]*' | sed 's/p(95)=//' | head -1
}
extract_p99() {
  echo "$1" | grep "http_req_duration" | grep -v "expected_response" | \
    grep -o 'p(99)=[0-9.]*' | sed 's/p(99)=//' | head -1
}
extract_actual_rps() {
  # "http_reqs...: 6001   100.01/s"  → last field before /s
  echo "$1" | grep "^    http_reqs\b" | \
    grep -o '[0-9.]*\/s' | grep -o '^[0-9.]*' | head -1
}
extract_total() {
  # Second-to-last field on the http_reqs line
  echo "$1" | grep "^    http_reqs\b" | \
    awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+$/) { print $i; exit } }' | head -1
}
extract_fail_pct() {
  echo "$1" | grep "http_req_failed" | grep -o '[0-9.]*%' | head -1
}

# ── Warm-up ───────────────────────────────────────────────────
echo "[openloop] Warm-up: 20s at 50 req/s through gateway…"
k6 run --quiet \
  --env TARGET=gateway --env RATE=50 --env DURATION=20s --env ENDPOINT="$ENDPOINT" \
  --summary-trend-stats="med,p(95),p(99)" \
  /bench/open-loop.js > /dev/null 2>&1 || true
k6 run --quiet \
  --env TARGET=upstream --env RATE=50 --env DURATION=20s --env ENDPOINT="$ENDPOINT" \
  --summary-trend-stats="med,p(95),p(99)" \
  /bench/open-loop.js > /dev/null 2>&1 || true
sleep 3
echo "[openloop] Warm-up done."
echo ""

# ── Fixed-rate runs ───────────────────────────────────────────
RUNS=""
FIRST=1
DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)

for rep in $(seq 1 $REPS); do
  for rate in $RATES; do
    for target in gateway upstream; do
      echo "[openloop] Rep $rep/$REPS  ${target}  ${rate} rps  ${DURATION}"

      TMPFILE=$(mktemp)
      k6 run \
        --env TARGET=$target --env RATE=$rate --env DURATION=$DURATION --env ENDPOINT="$ENDPOINT" \
        --summary-trend-stats="med,p(95),p(99)" \
        /bench/open-loop.js > "$TMPFILE" 2>&1 || true

      P50=$(extract_med "$(cat "$TMPFILE")")
      P95=$(extract_p95 "$(cat "$TMPFILE")")
      P99=$(extract_p99 "$(cat "$TMPFILE")")
      TOTAL=$(extract_total "$(cat "$TMPFILE")")
      ACTUAL_RPS=$(extract_actual_rps "$(cat "$TMPFILE")")
      FAIL_PCT=$(extract_fail_pct "$(cat "$TMPFILE")")

      [ -z "$P50" ] && P50=0
      [ -z "$P95" ] && P95=0
      [ -z "$P99" ] && P99=0
      [ -z "$TOTAL" ] && TOTAL=0
      [ -z "$ACTUAL_RPS" ] && ACTUAL_RPS=0
      [ -z "$FAIL_PCT" ] && FAIL_PCT="0%"

      # Validate achieved rate within 5% of requested
      # k6 constant-arrival-rate always achieves exactly the configured rate
      # unless the system cannot keep up (overload). Actual_rps from k6 output
      # is the iteration rate; it should equal $rate ± 5%
      RATE_LOW=$(echo "$rate" | awk '{printf "%.1f", $1 * 0.95}')
      RATE_HIGH=$(echo "$rate" | awk '{printf "%.1f", $1 * 1.05}')
      VALID="yes"
      # Compare numerically
      TOO_LOW=$(echo "$ACTUAL_RPS $RATE_LOW" | awk '{print ($1 < $2) ? "1" : "0"}')
      TOO_HIGH=$(echo "$ACTUAL_RPS $RATE_HIGH" | awk '{print ($1 > $2) ? "1" : "0"}')
      [ "$TOO_LOW" = "1" ] && VALID="no"
      [ "$TOO_HIGH" = "1" ] && VALID="no"

      echo "  reqs=${TOTAL}  actual=${ACTUAL_RPS}rps  p50=${P50}ms p95=${P95}ms p99=${P99}ms  fail=${FAIL_PCT}  valid=${VALID}"

      rm -f "$TMPFILE"

      ENTRY="{\"rep\":${rep},\"target\":\"${target}\",\"rate\":${rate},\"total_reqs\":${TOTAL},\"actual_rps\":${ACTUAL_RPS},\"p50_ms\":${P50},\"p95_ms\":${P95},\"p99_ms\":${P99},\"fail_pct\":\"${FAIL_PCT}\",\"valid\":\"${VALID}\"}"
      if [ "$FIRST" = "1" ]; then
        RUNS="$ENTRY"; FIRST=0
      else
        RUNS="${RUNS},${ENTRY}"
      fi

      sleep 2
    done
  done
done

# ── Saturation ramp ───────────────────────────────────────────
echo ""
echo "[openloop] Saturation ramp: 300 req/s for 60s through gateway"
echo "  (finding approximate saturation point; not averaged over reps)"
RAMP_TMP=$(mktemp)
k6 run \
  --env TARGET=gateway --env RATE=300 --env DURATION=60s --env ENDPOINT="$ENDPOINT" \
  --summary-trend-stats="med,p(95),p(99)" \
  /bench/open-loop.js > "$RAMP_TMP" 2>&1 || true
RAMP_P50=$(extract_med "$(cat "$RAMP_TMP")")
RAMP_P95=$(extract_p95 "$(cat "$RAMP_TMP")")
RAMP_P99=$(extract_p99 "$(cat "$RAMP_TMP")")
RAMP_RPS=$(extract_actual_rps "$(cat "$RAMP_TMP")")
RAMP_FAIL=$(extract_fail_pct "$(cat "$RAMP_TMP")")
[ -z "$RAMP_P50" ] && RAMP_P50=0
[ -z "$RAMP_P95" ] && RAMP_P95=0
[ -z "$RAMP_P99" ] && RAMP_P99=0
[ -z "$RAMP_RPS" ] && RAMP_RPS=0
[ -z "$RAMP_FAIL" ] && RAMP_FAIL="0%"
echo "  300 rps: actual=${RAMP_RPS}rps  p50=${RAMP_P50}ms  p95=${RAMP_P95}ms  p99=${RAMP_P99}ms  fail=${RAMP_FAIL}"
echo "  (target-app: single uvicorn worker; add --workers 2+ for production)"
rm -f "$RAMP_TMP"

# ── Write JSON ────────────────────────────────────────────────
echo "{\"date\":\"${DATE}\",\"tool\":\"k6\",\"executor\":\"constant-arrival-rate\",\"endpoint\":\"${ENDPOINT}\",\"duration\":\"${DURATION}\",\"reps\":${REPS},\"saturation_300rps\":{\"actual_rps\":${RAMP_RPS},\"p50_ms\":${RAMP_P50},\"p95_ms\":${RAMP_P95},\"p99_ms\":${RAMP_P99},\"fail_pct\":\"${RAMP_FAIL}\"},\"runs\":[${RUNS}]}" > "${OUT}"
echo ""
echo "[openloop] Results → ${OUT}"

# ── Per-run table ─────────────────────────────────────────────
echo ""
echo "=== Per-run detail (all runs) ==="
printf "%-10s %-4s %-4s %8s %8s %8s %10s %5s %6s\n" Target Rate Rep p50ms p95ms p99ms ActRps Fail Valid
printf "%-10s %-4s %-4s %8s %8s %8s %10s %5s %6s\n" ------ ---- --- ----- ----- ----- ------ ---- -----
jq -r '.runs[] | "\(.target) \(.rate) \(.rep) \(.p50_ms) \(.p95_ms) \(.p99_ms) \(.actual_rps) \(.fail_pct) \(.valid)"' "${OUT}" 2>/dev/null | \
  while read t r rp p50 p95 p99 rps fp v; do
    printf "%-10s %-4s %-4s %8s %8s %8s %10s %5s %6s\n" "$t" "$r" "$rp" "$p50" "$p95" "$p99" "$rps" "$fp" "$v"
  done

# ── Median of valid runs ───────────────────────────────────────
echo ""
echo "=== Median of valid runs ==="
printf "%-10s %-4s %8s %8s %8s %10s %5s\n" Target Rate p50ms p95ms p99ms ActRps nValid
printf "%-10s %-4s %8s %8s %8s %10s %5s\n" ------ ---- ----- ----- ----- ------ ------
for target in gateway upstream; do
  for rate in $RATES; do
    N_VALID=$(jq -r ".runs[] | select(.target==\"$target\" and .rate==$rate and .valid==\"yes\") | .p50_ms" "${OUT}" 2>/dev/null | wc -l | tr -d ' ')
    MED_P50=$(jq -r ".runs[] | select(.target==\"$target\" and .rate==$rate and .valid==\"yes\") | .p50_ms" "${OUT}" 2>/dev/null | sort -n | awk "NR==int($N_VALID/2)+1")
    MED_P95=$(jq -r ".runs[] | select(.target==\"$target\" and .rate==$rate and .valid==\"yes\") | .p95_ms" "${OUT}" 2>/dev/null | sort -n | awk "NR==int($N_VALID/2)+1")
    MED_P99=$(jq -r ".runs[] | select(.target==\"$target\" and .rate==$rate and .valid==\"yes\") | .p99_ms" "${OUT}" 2>/dev/null | sort -n | awk "NR==int($N_VALID/2)+1")
    MED_RPS=$(jq -r ".runs[] | select(.target==\"$target\" and .rate==$rate and .valid==\"yes\") | .actual_rps" "${OUT}" 2>/dev/null | sort -n | awk "NR==int($N_VALID/2)+1")
    printf "%-10s %-4s %8s %8s %8s %10s %5s/3\n" "$target" "$rate" "${MED_P50:--}" "${MED_P95:--}" "${MED_P99:--}" "${MED_RPS:--}" "$N_VALID"
  done
done

# ── Gateway vs upstream overhead ──────────────────────────────
echo ""
echo "=== Gateway overhead (gateway_p50_median - upstream_p50_median) ==="
echo "NOTE: If values change sign or spread > 2× the measurement, report"
echo "      'overhead not characterized' per AGENTS.md methodology rules."
GW_50_50=$(jq -r '.runs[] | select(.target=="gateway"  and .rate==50  and .valid=="yes") | .p50_ms' "${OUT}" 2>/dev/null | sort -n | awk 'NR==2')
UP_50_50=$(jq -r '.runs[] | select(.target=="upstream" and .rate==50  and .valid=="yes") | .p50_ms' "${OUT}" 2>/dev/null | sort -n | awk 'NR==2')
GW100_50=$(jq -r '.runs[] | select(.target=="gateway"  and .rate==100 and .valid=="yes") | .p50_ms' "${OUT}" 2>/dev/null | sort -n | awk 'NR==2')
UP100_50=$(jq -r '.runs[] | select(.target=="upstream" and .rate==100 and .valid=="yes") | .p50_ms' "${OUT}" 2>/dev/null | sort -n | awk 'NR==2')
GW200_50=$(jq -r '.runs[] | select(.target=="gateway"  and .rate==200 and .valid=="yes") | .p50_ms' "${OUT}" 2>/dev/null | sort -n | awk 'NR==2')
UP200_50=$(jq -r '.runs[] | select(.target=="upstream" and .rate==200 and .valid=="yes") | .p50_ms' "${OUT}" 2>/dev/null | sort -n | awk 'NR==2')

calc_overhead() {
  local gw="$1" up="$2" rate="$3"
  if [ -n "$gw" ] && [ -n "$up" ] && [ "$gw" != "0" ] && [ "$up" != "0" ]; then
    overhead=$(echo "$gw $up" | awk '{printf "%.2f", $1 - $2}')
    echo "  ${rate} rps: gateway=${gw}ms upstream=${up}ms  overhead=${overhead}ms"
  else
    echo "  ${rate} rps: data missing — overhead not characterized"
  fi
}
calc_overhead "$GW_50_50" "$UP_50_50" 50
calc_overhead "$GW100_50" "$UP100_50" 100
calc_overhead "$GW200_50" "$UP200_50" 200
