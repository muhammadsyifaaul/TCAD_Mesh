#!/usr/bin/env bash
set -euo pipefail
PASS=0; FAIL=0
ok()   { echo "  OK: $*";   PASS=$((PASS+1)); }
fail() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }

for url in \
  "http://localhost:8080/health::gateway" \
  "http://localhost:3000/health::dashboard" \
  "http://localhost:3000/stats::control-api-proxy"; do
  endpoint="${url%%::*}"; name="${url##*::}"
  CODE=$(curl -sf -o /dev/null -w "%{http_code}" "$endpoint")
  echo "  DEBUG: $name CODE=$CODE"
  [[ "$CODE" == "200" ]] && ok "$name → $CODE" || fail "$name → $CODE"
done
echo "PASS=$PASS FAIL=$FAIL"
