#!/usr/bin/env bash
set -uo pipefail
export MSYS_NO_PATHCONV=1
PASS=0; FAIL=0
ok()  { echo "  OK  $*"; PASS=$((PASS+1)); }
fail(){ echo "  FAIL $*"; FAIL=$((FAIL+1)); }
echo "testing docker info"
if docker info > /dev/null 2>&1; then
  echo "docker info succeeded"
  ok "Docker daemon running"
else
  echo "docker info FAILED rc=$?"
  fail "Docker daemon not running"
fi
echo "done PASS=$PASS"
