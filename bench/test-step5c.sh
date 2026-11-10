#!/usr/bin/env bash
set -euo pipefail
PASS=0; FAIL=0
ok() { echo "OK: $*" || true; PASS=$((PASS+1)); }
fail() { echo "FAIL: $*" || true; FAIL=$((FAIL+1)); }

echo "start"
CODE=$(curl -sf -o /dev/null -w "%{http_code}" "http://localhost:8080/health" || echo "FAILED")
echo "CODE=$CODE"
[[ "$CODE" == "200" ]] && ok "gateway 200" || fail "gateway $CODE"
echo "end PASS=$PASS FAIL=$FAIL"
