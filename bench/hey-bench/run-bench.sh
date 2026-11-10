#!/usr/bin/env sh
# bench/hey-bench/run-bench.sh
# In-network latency benchmark using hey (Go load generator).
#
# Runs from inside the Docker mesh network. Measures gateway and upstream
# (target-app) at 100/250/500 req/s for 30 seconds each, repeated 3 times,
# with a 5-second warm-up.
#
# Usage:
#   docker compose --profile bench run --rm --entrypoint sh hey-bench /bench/run-bench.sh
#
# Output: results to /results/bench_latency.json + stdout summary

set -eu

GATEWAY="http://gateway:8080"
UPSTREAM="http://target-app:8001"
ENDPOINT="/api/v1/shipments"
RATES="100 250 500"
DURATION=30
REPS=3

OUT="/results/bench_latency.json"
mkdir -p "$(dirname "$OUT")"

# ── Warm-up: prime connection pools ───────────────────────────
echo "[bench] Warm-up: 50 req/s for 5s through gateway…"
hey -n 250 -c 10 -q 50 -t 10 "${GATEWAY}${ENDPOINT}" > /dev/null 2>&1 || true
hey -n 250 -c 10 -q 50 -t 10 "${UPSTREAM}${ENDPOINT}" > /dev/null 2>&1 || true
sleep 2

echo "[bench] Starting: ${REPS} reps × ${RATES} rps × ${DURATION}s"
echo "[bench] Endpoint: ${ENDPOINT}"
echo ""

# hey text output has lines like:
#   50%% in 0.0045 secs
# We extract the number after "in" and convert to ms.
# hey shows: 10, 25, 50, 75, 90, 95, 99 percentile lines.
# With small N, 95 and 99 may show 0.0000 — that's valid.
extract_pct_ms() {
  local pct="$1" file="$2"
  # Match "  50%% in 0.0045 secs" — busybox grep doesn't support \s
  grep " ${pct}%% in " "$file" 2>/dev/null | head -1 | awk '{printf "%.2f", $3 * 1000}'
}

extract_rps() {
  grep "Requests/sec:" "$1" 2>/dev/null | awk '{printf "%.1f", $2}'
}

extract_ok() {
  grep "\[200\]" "$1" 2>/dev/null | head -1 | sed 's/.*\[200\].*//' | awk '{print $1}' | tr -cd '0-9'
}

# ── Run benchmark ─────────────────────────────────────────────
RUNS_JSON=""

for rep in $(seq 1 $REPS); do
  for rate in $RATES; do
    for target_label in gateway upstream; do
      if [ "$target_label" = "gateway" ]; then
        URL="${GATEWAY}${ENDPOINT}"
      else
        URL="${UPSTREAM}${ENDPOINT}"
      fi

      N=$((rate * DURATION))
      echo "[bench] Rep $rep/$REPS  ${target_label}  ${rate} rps  ${DURATION}s  N=$N"

      TMPFILE=$(mktemp)
      hey -n "$N" -c 50 -q "$rate" -t 10 "$URL" > "$TMPFILE" 2>&1 || true

      P50_MS=$(extract_pct_ms 50 "$TMPFILE")
      P95_MS=$(extract_pct_ms 95 "$TMPFILE")
      P99_MS=$(extract_pct_ms 99 "$TMPFILE")
      RPS_VAL=$(extract_rps "$TMPFILE")
      OK_VAL=$(extract_ok "$TMPFILE")
      [ -z "$OK_VAL" ] && OK_VAL=0
      [ -z "$P50_MS" ] && P50_MS=0
      [ -z "$P95_MS" ] && P95_MS=0
      [ -z "$P99_MS" ] && P99_MS=0
      [ -z "$RPS_VAL" ] && RPS_VAL=0

      echo "  p50=${P50_MS}ms p95=${P95_MS}ms p99=${P99_MS}ms actual=${RPS_VAL}rps ok=${OK_VAL}"

      # Build JSON array element
      RUN="{\"rep\":${rep},\"target\":\"${target_label}\",\"rate\":${rate},\"duration_s\":${DURATION},\"p50_ms\":${P50_MS},\"p95_ms\":${P95_MS},\"p99_ms\":${P99_MS},\"actual_rps\":${RPS_VAL},\"status_200\":${OK_VAL}}"
      if [ -z "$RUNS_JSON" ]; then
        RUNS_JSON="$RUN"
      else
        RUNS_JSON="${RUNS_JSON},${RUN}"
      fi

      rm -f "$TMPFILE"
      sleep 1
    done
  done
done

# ── Write JSON ─────────────────────────────────────────────────
DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "{\"date\":\"${DATE}\",\"endpoint\":\"${ENDPOINT}\",\"duration_s\":${DURATION},\"reps\":${REPS},\"runs\":[${RUNS_JSON}]}" > "${OUT}"
echo ""
echo "[bench] Results saved to ${OUT}"

# ── Summary: median across reps ────────────────────────────────
echo ""
echo "=== Summary (median across ${REPS} reps, ${DURATION}s per run) ==="
echo ""
printf "%-10s %-6s %8s %8s %8s %10s\n" "Target" "Rate" "p50(ms)" "p95(ms)" "p99(ms)" "Act rps"
printf "%-10s %-6s %8s %8s %8s %10s\n" "------" "----" "-------" "-------" "-------" "-------"

for target in gateway upstream; do
  for rate in $RATES; do
    P50_MED=$(jq -r ".runs[] | select(.target==\"$target\" and .rate==$rate) | .p50_ms" "${OUT}" | sort -n | sed -n '2p')
    P95_MED=$(jq -r ".runs[] | select(.target==\"$target\" and .rate==$rate) | .p95_ms" "${OUT}" | sort -n | sed -n '2p')
    P99_MED=$(jq -r ".runs[] | select(.target==\"$target\" and .rate==$rate) | .p99_ms" "${OUT}" | sort -n | sed -n '2p')
    ACT_MED=$(jq -r ".runs[] | select(.target==\"$target\" and .rate==$rate) | .actual_rps" "${OUT}" | sort -n | sed -n '2p')
    printf "%-10s %-6s %8s %8s %8s %10s\n" "$target" "$rate" "$P50_MED" "$P95_MED" "$P99_MED" "$ACT_MED"
  done
done

echo ""
echo "=== Per-run detail ==="
jq -r '.runs[] | "\(.target) r=\(.rate) rep=\(.rep): p50=\(.p50_ms)ms p95=\(.p95_ms)ms p99=\(.p99_ms)ms actual=\(.actual_rps)rps ok=\(.status_200)"' "${OUT}"

# ── CPU check ──────────────────────────────────────────────────
echo ""
echo "=== CPU note ==="
echo "Load generator: hey (Go, compiled binary, low CPU overhead)"
echo "Concurrency: 50 goroutines per run"
echo "If actual_rps >> requested rate, the load generator is NOT the bottleneck."
