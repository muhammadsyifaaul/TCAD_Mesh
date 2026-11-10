#!/usr/bin/env bash
# scripts/wait-healthy.sh
# Polls docker compose ps until every non-redis service reports "healthy".
# Exits 0 on success, 1 after timeout.

set -euo pipefail

TIMEOUT=${HEALTH_TIMEOUT:-120}   # seconds
INTERVAL=3
ELAPSED=0

SERVICES=(gateway target-app honeypot control-api dashboard)

echo "Waiting for services to become healthy (timeout: ${TIMEOUT}s)..."

while true; do
  ALL_HEALTHY=true

  for svc in "${SERVICES[@]}"; do
    STATUS=$(docker compose ps --format json 2>/dev/null \
      | python -c "
import sys, json
data = sys.stdin.read().strip()
# docker compose ps --format json outputs one JSON object per line (not a JSON array)
for line in data.splitlines():
    try:
        obj = json.loads(line)
        if obj.get('Service') == '${svc}' or obj.get('Name','').endswith('${svc}'):
            print(obj.get('Health', 'unknown'))
    except:
        pass
" 2>/dev/null || echo "unknown")

    if [[ "$STATUS" != "healthy" ]]; then
      ALL_HEALTHY=false
      echo "  [${ELAPSED}s] ${svc}: ${STATUS:-unknown}"
    fi
  done

  if $ALL_HEALTHY; then
    echo ""
    echo "✅  All services are healthy."
    exit 0
  fi

  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))

  if [[ $ELAPSED -ge $TIMEOUT ]]; then
    echo ""
    echo "❌  Timeout after ${TIMEOUT}s. Run 'docker compose ps' to inspect."
    exit 1
  fi
done
