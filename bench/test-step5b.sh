#!/usr/bin/env bash
# Identical to clean-room-test.sh step 5 but with maximum debugging
set -euo pipefail

PASS=0; FAIL=0
_green() { printf '\033[32m%s\033[0m\n' "$*"; }
_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
ok()     { _green "  OK: $*"; PASS=$((PASS+1)); }
fail()   { _red   "  FAIL: $*"; FAIL=$((FAIL+1)); }

echo "Before loop, PASS=$PASS FAIL=$FAIL"

for url in \
  "http://localhost:8080/health::gateway" \
  "http://localhost:3000/health::dashboard" \
  "http://localhost:3000/stats::proxy"; do
  endpoint="${url%%::*}"
  name="${url##*::}"
  echo "Checking $name at $endpoint"
  CODE=$(curl -sf -o /dev/null -w "%{http_code}" "$endpoint" 2>/dev/null)
  RC=$?
  echo "curl returned CODE=$CODE RC=$RC"
  if [[ "$CODE" == "200" ]]; then
    ok "$name → $CODE"
  else
    fail "$name → $CODE"
  fi
  echo "After check: PASS=$PASS FAIL=$FAIL"
done

echo "Loop done. PASS=$PASS FAIL=$FAIL"
