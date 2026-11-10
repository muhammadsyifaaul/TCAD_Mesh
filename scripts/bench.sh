#!/usr/bin/env bash
# scripts/bench.sh
# Runs the TCAD Mesh benchmark harness against live Docker services,
# then generates results/SUMMARY.md from the output.
#
# Prerequisites: docker compose up --build -d  (all services healthy)
# Usage:         bash scripts/bench.sh
# Output:        results/bench.json  +  results/SUMMARY.md

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

_bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
_green() { printf '\033[32m%s\033[0m\n' "$*"; }
_red()   { printf '\033[31m%s\033[0m\n' "$*"; }

_bold "════════════════════════════════════════"
_bold " TCAD Mesh — Benchmark Harness"
_bold "════════════════════════════════════════"

# ── Preflight ──────────────────────────────────────────────────────────────────
echo ""
echo "→ Checking gateway health…"
if ! curl -sf http://localhost:8080/health > /dev/null 2>&1; then
  _red "FATAL: gateway not healthy. Run 'docker compose up -d' first."
  exit 1
fi
_green "  Gateway is healthy."

# ── Build bench image ──────────────────────────────────────────────────────────
echo ""
echo "→ Building bench image…"
docker compose build bench 2>/dev/null || \
  docker build -t tcad_mesh-bench ./bench

# ── Run benchmark inside Docker network ───────────────────────────────────────
echo ""
_bold "Running benchmarks (this takes ~2 minutes)…"
echo ""

# Load env vars for benchmark config
TARPIT_MS=$(grep '^TARPIT_DELAY_MS=' .env 2>/dev/null | cut -d= -f2 || echo 3000)
TARPIT_MAX=$(grep '^TARPIT_MAX_CONCURRENT=' .env 2>/dev/null | cut -d= -f2 || echo 50)
ENUM_THR=$(grep '^ENUM_THRESHOLD=' .env 2>/dev/null | cut -d= -f2 || echo 5)

mkdir -p results

docker run --rm \
  --network tcad_mesh_mesh \
  -v "$(pwd)/results:/results" \
  -e GATEWAY_URL=http://gateway:8080 \
  -e CONTROL_URL=http://control-api:8003 \
  -e TARPIT_DELAY_MS="${TARPIT_MS}" \
  -e TARPIT_MAX_CONCURRENT="${TARPIT_MAX}" \
  -e ENUM_THRESHOLD="${ENUM_THR}" \
  -e RESULTS_PATH=/results/bench.json \
  tcad_mesh-bench ${PYTHON:-python} bench.py 2>&1

echo ""
echo "→ Benchmark complete."

# ── Generate SUMMARY.md ────────────────────────────────────────────────────────
echo ""
echo "→ Generating results/SUMMARY.md…"
${PYTHON:-python} bench/write_summary.py 2>&1 || \
  docker run --rm \
    -v "$(pwd)/results:/results" \
    -e BENCH_JSON=/results/bench.json \
    -e SUMMARY_PATH=/results/SUMMARY.md \
    tcad_mesh-bench ${PYTHON:-python} write_summary.py

echo ""
_bold "════════════════════════════════════════"
_green "✅  Benchmark complete!"
echo "    JSON  → results/bench.json"
echo "    Report→ results/SUMMARY.md"
_bold "════════════════════════════════════════"
